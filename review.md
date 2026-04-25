# Review Results

## Findings

1. P3 - `PROJECT_STATUS.md:101` still documents runtime `pixivpy3` auto-install.
   - Current implementation no longer attempts `pip3 install pixivpy3` at service start. `Makefile` bundles `pixivpy3` and related wheels into `/usr/share/pixiv-backup/vendor`, and `src/init.d/pixiv-backup` only checks imports via `check_python_deps`.
   - Recommended fix: change the line to say startup verifies Python dependencies from package/vendor installation and asks operators to reinstall the package if they are missing.

2. P3 - `PROJECT_STATUS.md:110` and `PROJECT_STATUS.md:117` describe LuCI start as always calling `pixiv-backup trigger`.
   - Current controller behavior is conditional: if `/etc/init.d/pixiv-backup running` succeeds, `action_start()` calls `pixiv-backup trigger`; otherwise it calls `pixiv-backup start --force-run`.
   - Recommended fix: document the conditional behavior for both the route and the "立即开始备份" button. This matters because `trigger` only writes `force_run.flag` and does not start a stopped service.

## Notes

- I did not review untracked `features.md`; it is outside the tracked diff shown by `git status`.
- Existing user change `PROJECT_STATUS.md` remains unmodified by this review pass.
