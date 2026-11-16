from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import quoteattr
from zipfile import ZipFile, ZIP_DEFLATED

from pipeline import public_macro_import as importer


class PublicMacroImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def board(self, release, override=None, observations=None):
        parts = ['<Root xmlns="urn:test"><DataSet>']
        for key, (name, attributes, _) in importer.BOARD[release].items():
            attrs = {'SERIES_NAME': name, **attributes, **(override or {})}
            parts.append('<Series ' + ' '.join(f'{k}={quoteattr(v)}' for k,v in attrs.items()) + '>')
            stamp = '2026-09' if release == 'h6' else '2026-11-11'
            parts.extend(observations or [f'<Obs OBS_STATUS="A" TIME_PERIOD="{stamp}" OBS_VALUE="2000"/>'])
            parts.append('</Series>')
        parts.append('<Series SERIES_NAME="irrelevant"><Obs TIME_PERIOD="other format" OBS_VALUE="not numeric"/></Series>')
        parts.append('</DataSet></Root>')
        path = self.root / (release + '.zip')
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            archive.writestr(release.upper() + '_data.xml', ''.join(parts))
        return path

    def operation(self, identifier='1', amount=325000000, stamp='2026-11-13', **changes):
        return {'operationId':identifier, 'operationType':'Reverse Repo','term':'Overnight',
                'operationDate':stamp,'details':[{'securityType':'Treasury','amtAccepted':amount}], **changes}

    def receipts(self):
        result = {key: {'source_url':importer.board_url(rel), 'series_id':spec[0], 'sha256':'a'*64}
                  for rel, specs in importer.BOARD.items() for key,spec in specs.items()}
        result['rrp'] = {'source_url':importer.RRP_URL,'series_id':'overnight_treasury_rrp','sha256':'b'*64}
        return result

    def test_metadata_scaling_month_and_status(self):
        for release in importer.BOARD:
            result = importer.parse_board_zip(self.board(release),release)
            for key, rows in result.items():
                self.assertEqual(rows, [('2026-09-01' if key=='m2' else '2026-11-11',
                                         2000.0)])
        obs = ['<Obs OBS_STATUS="ND" TIME_PERIOD="2026-11-10"/>',
               '<Obs OBS_STATUS="NA" TIME_PERIOD="2026-11-09"/>',
               '<Obs OBS_STATUS="NC" TIME_PERIOD="2026-11-08"/>',
               '<Obs OBS_STATUS="A" TIME_PERIOD="2026-11-11" OBS_VALUE="4.86"/>']
        self.assertEqual(importer.parse_board_zip(self.board('h15',observations=obs),'h15')['us2y'], [('2026-11-11',4.86)])
        actual_month = ['<Obs OBS_STATUS="A" TIME_PERIOD="2026-09-30" OBS_VALUE="23413.9"/>']
        self.assertEqual(importer.parse_board_zip(self.board('h6',observations=actual_month),'h6')['m2'], [('2026-09-01',23413.9)])

    def test_bad_units_frequency_adjustment_dates_and_values_fail(self):
        for override in ({'UNIT_MULT':'1000'}, {'FREQ':'8'}, {'UNIT':'unknown'}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                importer.parse_board_zip(self.board('h15',override=override),'h15')
        with self.assertRaises(ValueError):
            importer.parse_board_zip(self.board('h6',override={'ADJUSTED':'NSA'}),'h6')
        for stamp, value, status in [('2026-02-30','1','A'),('2026-1-01','1','A'),
                                     ('2026-11-11','NaN','A'),('2026-11-11','inf','A'),
                                     ('2026-11-11','wrong','A'),('2026-11-11','1','X')]:
            with self.subTest(stamp=stamp,value=value,status=status), self.assertRaises(ValueError):
                importer.parse_board_zip(self.board('h15',observations=[f'<Obs TIME_PERIOD="{stamp}" OBS_VALUE="{value}" OBS_STATUS="{status}"/>']),'h15')

    def test_duplicate_observations_and_size_limits(self):
        obs='<Obs TIME_PERIOD="2026-11-11" OBS_VALUE="1" OBS_STATUS="A"/>'
        with self.assertRaises(ValueError):
            importer.parse_board_zip(self.board('h15',observations=[obs,obs]),'h15')
        path=self.board('h15')
        with patch.object(importer,'MAX_ZIP',1), self.assertRaises(ValueError):
            importer.parse_board_zip(path,'h15')
        with patch.object(importer,'MAX_XML',1), self.assertRaises(ValueError):
            importer.parse_board_zip(path,'h15')
        with ZipFile(path,'w') as archive:
            archive.writestr('H15_data.xml','<!DOCTYPE Root [<!ENTITY x "expanded">]><Root/>')
        with self.assertRaises(ValueError): importer.parse_board_zip(path,'h15')

    def test_utf16_dtd_cannot_bypass_ascii_declaration_check(self):
        source = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE Root [<!ENTITY x "expanded">]><Root>&x;</Root>'
        for encoding in ('utf-16', 'utf-16-le', 'utf-16-be', 'utf-32'):
            path=self.root/'encoded.zip'
            with ZipFile(path,'w',ZIP_DEFLATED) as archive:
                archive.writestr('H15_data.xml',source.encode(encoding))
            with self.subTest(encoding=encoding), self.assertRaisesRegex(ValueError,'UTF-8'):
                importer.parse_board_zip(path,'h15')

    def test_depth_and_total_observations_include_unselected_data(self):
        path=self.root/'bounded.zip'
        with ZipFile(path,'w',ZIP_DEFLATED) as archive:
            archive.writestr('H15_data.xml','<Root>'+'<Nested>'*32+'</Nested>'*32+'</Root>')
        with self.assertRaisesRegex(ValueError,'depth limit'):
            importer.parse_board_zip(path,'h15')
        with ZipFile(path,'w',ZIP_DEFLATED) as archive:
            archive.writestr('H15_data.xml','<Root><Series SERIES_NAME="not-selected"><Obs/><Obs/><Obs/></Series></Root>')
        with patch.object(importer,'MAX_OBSERVATIONS',2),self.assertRaisesRegex(ValueError,'Observation count'):
            importer.parse_board_zip(path,'h15')

    def test_rrp_filters_tranches_and_aggregates_unique_operations_by_date(self):
        payload={'repo':{'operations':[
            self.operation(), self.operation('2',250000000),
            self.operation('3',term='Term'), self.operation('4',operationType='Repo'),
            self.operation('5',details=[{'securityType':'Agency','amtAccepted':999999999}]),
            self.operation('6',0,stamp='2026-11-12'),
        ]}}
        self.assertEqual(importer.parse_rrp(payload),{'rrp':[('2026-11-12',0),('2026-11-13',0.575)]})
        for operations in ([self.operation(),self.operation()], [self.operation(amount=float('nan'))],
                           [self.operation(amount=-1)], [self.operation(stamp='2026-02-30')],
                           [self.operation(details=[])]):
            with self.subTest(operations=operations), self.assertRaises(ValueError):
                importer.parse_rrp({'repo':{'operations':operations}})

    def test_snapshot_is_new_atomic_verified_and_bounded(self):
        output=self.root/'snapshot.sqlite'
        points=[((date(2025,1,1)+timedelta(days=i)).isoformat(),float(i)) for i in range(405)]
        series={key:points for key in importer.INDICATORS}
        importer.write_snapshot(output,series,self.receipts())
        self.assertEqual(output.stat().st_mode & 0o777,0o600)
        conn=sqlite3.connect(output); self.addCleanup(conn.close)
        self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone(),('ok',))
        self.assertEqual(conn.execute('SELECT value FROM meta WHERE key="schema"').fetchone(),(importer.SCHEMA,))
        self.assertEqual(conn.execute('SELECT count(*) FROM market_indicators').fetchone(),(2400,))
        self.assertEqual(conn.execute('SELECT min(snapshot_date) FROM market_indicators').fetchone(),(points[5][0],))
        self.assertEqual(conn.execute('SELECT count(*) FROM source_receipts').fetchone(),(6,))
        before=output.read_bytes()
        with self.assertRaises(FileExistsError): importer.write_snapshot(output,series,self.receipts())
        self.assertEqual(before,output.read_bytes())
        self.assertEqual(list(self.root.glob('.public-macro-*')),[])
        invalid=self.receipts();invalid['rrp']['source_url']='https://fred.stlouisfed.org/series/RRPONTSYD'
        with self.assertRaises(ValueError):importer.write_snapshot(self.root/'bad.sqlite',series,invalid)
        self.assertFalse((self.root/'bad.sqlite').exists())
        with self.assertRaises(ValueError):importer.write_snapshot(self.root/'empty.sqlite',{**series,'m2':[]},self.receipts())
        self.assertFalse((self.root/'empty.sqlite').exists())

    def test_destination_created_during_publish_is_preserved(self):
        output=self.root/'raced.sqlite'
        series={key:[('2026-11-11',1)] for key in importer.INDICATORS}
        real_link=importer.os.link
        def race(source,destination):
            Path(destination).write_bytes(b'other writer')
            return real_link(source,destination)
        with patch.object(importer.os,'link',side_effect=race),self.assertRaises(FileExistsError):
            importer.write_snapshot(output,series,self.receipts())
        self.assertEqual(output.read_bytes(),b'other writer')
        self.assertEqual(list(self.root.glob('.public-macro-*')),[])
