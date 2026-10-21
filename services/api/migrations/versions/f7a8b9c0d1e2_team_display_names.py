"""Display team names in stored market titles, rules and outcome labels. Accepted picks keep their own snapshot."""
import sqlalchemy as sa
from alembic import op

from rift.display import team_name

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    teams = db.execute(sa.text("SELECT code, name FROM teams")).all()
    # Longest first, so "Hanwha Life Esports" is replaced before any shorter name inside it.
    for code, name in sorted(teams, key=lambda t: -len(t.name)):
        shown = team_name(code, name)
        if shown == name:
            continue
        args = {"old": name, "new": shown, "like": f"%{name}%"}
        db.execute(sa.text("UPDATE markets SET title = replace(title, :old, :new), "
                           "rules_text = replace(rules_text, :old, :new) "
                           "WHERE title LIKE :like OR rules_text LIKE :like"), args)
        db.execute(sa.text("UPDATE outcomes SET label = :new WHERE label = :old"), args)


def downgrade():
    pass  # display text only; the provider names are still on the teams table
