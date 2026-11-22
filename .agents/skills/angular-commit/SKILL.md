---
name: angular-commit
description: Create or revise a Git commit message in Angular style, or commit requested changes using that format.
---

# Angular commit messages

1. Read the repository’s instructions and inspect the intended diff. Use `git status --short` and `git diff --cached` for staged work. Inspect unstaged changes when the request includes them.
2. Write the header as `type(scope): subject`. Use a short lowercase scope for the affected component. Use an imperative subject that starts lowercase and ends without a period. Keep the header within 72 characters.
3. Pick a standard type that describes the change: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `style`, `chore`, or `revert`. Use the body for motivation or impact when needed. Add a `BREAKING CHANGE:` footer for an actual breaking change.
4. When asked to commit, stage only the intended changes, run the repository’s checks, then commit and verify the header with `git log -1 --format=%s`. Pushing and amending need separate authorization from the user’s request.

Example: `fix(validation): reject malformed bounding boxes`
