"""Legacy operator scope while explicit member ownership is being introduced."""


def legacy_groups_condition(conn) -> str:
    """SQL predicate for the fixed stock_groups alias `g`, not user input.

    Unmigrated schemas contain only legacy groups. Once the ownership column is
    provisioned, legacy readers must never consume a member's groups. Do not
    cache this check: a connection can survive explicit schema preparation.
    """
    columns = {row[1] for row in conn.execute('PRAGMA table_info(stock_groups)')}
    return 'g.owner_id IS NULL' if 'owner_id' in columns else '1=1'
