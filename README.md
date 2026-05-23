# Carl Ross Investing Journal - public site

Hugo static site, GitHub Pages deployment. Public-facing personal investing journal; no client assets, no advisory offer, no connection to the trading VPS or database.

## One-time setup

Install Hugo (extended, ≥ 0.139) and git. Then, from a fresh clone:

```bash
git submodule add --depth=1 https://github.com/adityatelange/hugo-PaperMod.git themes/PaperMod
git submodule update --init --recursive
```

PaperMod is pinned as a submodule so the GitHub Actions build fetches it reproducibly.

## Local preview

```bash
hugo server -D
```

Serves on `http://localhost:1313/` with draft posts included.

## Publishing a commentary post

```bash
hugo new commentary/2026-06.md
```

Edit the generated file, set `draft: false`, commit, push to `main`. GitHub Actions handles the deploy.

## Content approach

- **Public (this site):** monthly notes on process, risk, mistakes, results, and what comes next.
- **Private:** raw account records, trade logs, database snapshots, and evidence archives are maintained separately.

## Structure

```
config.toml                       site-wide config
archetypes/commentary.md          template for new commentary posts
content/
  commentary/                     monthly posts + section index
  about.md                        journal purpose and safety framing
  contact.md                      LinkedIn contact
  archive.md                      chronological list (PaperMod archives layout)
assets/css/custom.css             typography + disclaimer styling
layouts/partials/footer.html      disclaimer footer (every page)
layouts/partials/extend_head.html injects custom.css into PaperMod <head>
static/images/                    any images referenced from posts
.github/workflows/hugo.yml        build + deploy
themes/PaperMod/                  theme (submodule; not in repo directly)
```

## Edits to remember

Before first push, update `baseURL` in `config.toml` if it differs from default. Contact method in `content/contact.md` is set to LinkedIn.
