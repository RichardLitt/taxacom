# Taxacom Archive

A static, searchable mirror of the [TAXACOM](https://taxacom.org) mailing list archive (biological systematics, 1992–2025), formerly hosted at `lists.ku.edu`. That server no longer serves the archive.

The site lives at **https://taxacom.org**.

Old links keep working if you swap the domain:
`https://lists.ku.edu/pipermail/taxacom/2024-November/137850.html` → `https://taxacom.org/pipermail/taxacom/2024-November/137850.html`

## What the build does

`build.py` turns a Mailman 2 backup into the site:

- **Original pages:** copies the Pipermail HTML for the 166 months whose pages survived, converting every page to UTF-8. Message text is left byte-for-byte unchanged.
- **Missing months:** rebuilds the 232 months whose HTML was missing. Bodies come from each month's `.txt` mbox, and message numbers, threading and authors come from Pipermail's `database/<month>-article`. Each message therefore lands at the URL it had on `lists.ku.edu` (`pipermail_render.py`, `pipermail_db.py`).
- **Lost pages:** restores individual message pages that were missing from surviving months, such as most of 2006-June.
- **Duplicates:** repeat imports left up to three copies of many messages. The build keeps one copy of each and turns the others into small redirect pages, so every old URL still works (`dedupe.py`, issue #1).
- **Search:** adds a banner linking to search and browse, and marks message pages for [Pagefind](https://pagefind.app) full-text search.

Email addresses stay obscured (`user at domain`), as in the original public archive. The archive was public on `lists.ku.edu` (`archive_private = 0`).

## Build

You need the Mailman backup (not in this repo), Python 3.12+ and Node 20+.

```sh
python3 build.py /path/to/backup/archives/private/taxacom public
npx -y pagefind@1.5.2 --site public
```

Use Pagefind 1.5 or later. Earlier versions silently return only a fraction of the matches on an index this large.

**Never publish** the backup's `lists/` directory (it holds `config.pck` with subscriber addresses and passwords) or `archives/private/taxacom/database/`. The build reads but never copies them, and `test_site.py` fails if they appear in the output.

## Test

```sh
# Built site vs. the raw backup: privacy, URLs, completeness, content, encoding, links
python3 test_site.py /path/to/backup/archives/private/taxacom public

# Real searches against a server: local, or the live site
npx -y http-server@14.1.1 public -p 8642 &
node test_search.mjs http://127.0.0.1:8642
node test_search.mjs https://taxacom.org
```

Both print PASS/FAIL for each check and exit non-zero on failure. `test_search.mjs` needs only a URL, so it can check the live deployment.

## Deploy

GitHub Pages serves the built `public/` directory from the `gh-pages` branch, with `CNAME` set to `taxacom.org`. The site is about 700 MB in about 160k files, under GitHub Pages' 1 GB limit.

## Citation

This archive is available on Zenodo. If you are citing the archive, please cite:

> TAXACOM. (2026). TAXACOM 1992-2025 Backup [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.23352322

## License

The code is licensed under MIT. That having been said, this code has been run using Claude Opus 5.5, which means that the license may not be enforceable.

The content is not licensed by me. All submitters to the list accepted that it would be publicly available on the TAXACOM LISTSERV. Each user maintains copyright over their own content. I and my coorganizers recieved permission from the list owners to share these files as part of the TAXACOM reboot.

### Request deletion of files

If you would like your own emails to be removed from this archive, let us know.
