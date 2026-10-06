# Vendored Frappe skills

Every `frappe-*` skill directory here is copied unmodified from
https://github.com/Impertio-Studio/Frappe_Claude_Skill_Package
(commit `36cfa807518f48e4210fac2a5afc6adafad4c53e`, v3.2.0, 61 skills).

The upstream repository's LICENSE.md is LGPL-3.0 (its README and skill
frontmatter say MIT); the license text is kept in `FRAPPE_SKILLS_LICENSE.md`.

To update: re-copy `skills/source/*/*/` from upstream and bump the commit above.
Put project-specific skills in their own directories (not prefixed `frappe-`).
