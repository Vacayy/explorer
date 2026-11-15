"""Member-owned confirmed principles; no legacy schema, parser or alert side effects."""
import json
from pipeline import portfolio_principles as rules
from security.member_portfolio import MemberPortfolio


class PrincipleUnavailable(Exception):
    pass


class PrincipleInvalid(Exception):
    pass


class PrincipleLimit(Exception):
    pass


class MemberPrinciples(MemberPortfolio):
    @staticmethod
    def prepared(conn):
        conn.execute('SELECT group_id,text,rules_json,notes_json FROM member_portfolio_principles LIMIT 0')

    @staticmethod
    def projection(row):
        return {'id': row['id'], 'text': row['text'], 'created_at': row['created_at'],
                'rules': [{**rule, 'summary': rules.describe(rule)} for rule in json.loads(row['rules_json'])],
                'notes': json.loads(row['notes_json'])}

    @staticmethod
    def cleaned(body):
        try:
            clean = rules.validate([rule.model_dump(exclude={'summary'}) for rule in body.rules])
            notes = rules._clean_notes(body.notes)
            if not clean and not notes:
                raise ValueError()
            return body.text, json.dumps(clean), json.dumps(notes, ensure_ascii=False)
        except (ValueError, TypeError, KeyError):
            raise PrincipleInvalid() from None

    def listing(self):
        with self.connection() as conn:
            self.prepared(conn)
            return [self.projection(row) for row in conn.execute(
                'SELECT id,text,rules_json,notes_json,created_at FROM member_portfolio_principles WHERE group_id=? ORDER BY id',
                (self.group(conn),))]

    def create(self, body):
        values = self.cleaned(body)
        with self.connection(write=True) as conn:
            self.prepared(conn)
            gid = self.group(conn, create=True)
            if conn.execute('SELECT COUNT(*) FROM member_portfolio_principles WHERE group_id=?', (gid,)).fetchone()[0] >= 100:
                raise PrincipleLimit()
            return conn.execute('INSERT INTO member_portfolio_principles(group_id,text,rules_json,notes_json) VALUES(?,?,?,?)',
                                (gid, *values)).lastrowid

    def replace(self, principle_id, body):
        values = self.cleaned(body)
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('UPDATE member_portfolio_principles SET text=?,rules_json=?,notes_json=? WHERE id=? AND group_id=?',
                                (*values, principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()

    def update_text(self, principle_id, text):
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('UPDATE member_portfolio_principles SET text=? WHERE id=? AND group_id=?',
                                (text, principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()

    def delete(self, principle_id):
        with self.connection(write=True) as conn:
            self.prepared(conn)
            if not conn.execute('DELETE FROM member_portfolio_principles WHERE id=? AND group_id=?',
                                (principle_id, self.group(conn))).rowcount:
                raise PrincipleUnavailable()
