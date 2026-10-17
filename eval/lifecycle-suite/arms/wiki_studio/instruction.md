## Project wiki

This project keeps its curated knowledge in a wiki maintained with the
wiki-studio command-line tool, which is on PATH. The wiki is knowledge/wiki/:
index.md lists every page, log.md records every change, and each page is a
markdown file with frontmatter in a typed directory (decisions/, concepts/,
workflows/, playbooks/, incidents/, glossary/, open-questions/).

### Session start
  wiki-studio info
  wiki-studio find "<what you are about to do>"
Read knowledge/wiki/index.md and every page that find lists before you start.
find ranks pages by the words they share with your question, so use the words
of the task itself.

### Recording knowledge
Do not edit files under knowledge/wiki/ directly. For each recording, write a
fresh draft directory laid out like the wiki, then land it through the gate:
  wiki-studio init                  (once, if index.md or log.md is missing)
  D=$(mktemp -d); mkdir -p "$D/decisions"
  $D/decisions/<slug>.md   a page: frontmatter with page_type, slug (the file
      name), title, status: draft, last_reviewed (YYYY-MM-DD) and sources (at
      least one "- path: <file>"), then the body
  $D/index.md   one line: - [Title](decisions/<slug>.md) — summary
  $D/log.md     one line: - YYYY-MM-DD — created <slug> (decision)
  wiki-studio propose --from "$D" --promote
If propose refuses the draft, fix what it names and run it again. Use the
directory that fits the knowledge: decisions/ for a choice made, concepts/
for how something works, workflows/ for a procedure.

### Checking
  wiki-studio lint                  (zero violations expected)

### Never
- Run wiki-studio ingest or wiki-studio query: they start another model.
- Rewrite index.md or log.md; they only grow by the one-line appends above.
