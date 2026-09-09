#!/usr/bin/env bash
# =============================================================================
# GIT & GITHUB CHEATSHEET
# A fast reference for everyday Git workflows and the GitHub CLI (gh).
# Every command below is safe to read top-to-bottom; run individually, not
# as a script.
# =============================================================================


# =============================================================================
# 1. SETUP & CONFIG
# =============================================================================

git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global core.editor "code --wait"     # Set default editor
git config --list                                  # Show all config
git config --global alias.st status                 # Custom alias (git st)


# =============================================================================
# 2. STARTING & CLONING
# =============================================================================

git init                          # Create a new repo in current dir
git clone <url>                    # Clone a remote repo
git clone <url> --depth 1           # Shallow clone (latest commit only)
git clone -b branch_name <url>       # Clone a specific branch


# =============================================================================
# 3. BASIC WORKFLOW: STATUS, STAGE, COMMIT
# =============================================================================

git status                         # Show changed/staged/untracked files
git status -s                       # Short format

git add file.txt                    # Stage a specific file
git add .                            # Stage all changes in current dir
git add -p                           # Stage interactively, chunk by chunk

git diff                             # Unstaged changes vs last commit
git diff --staged                     # Staged changes vs last commit
git diff HEAD~1 HEAD                   # Diff between two commits
git diff branch1..branch2               # Diff between branches

git commit -m "message"                 # Commit staged changes
git commit -am "message"                 # Stage tracked changes + commit
git commit --amend -m "new message"       # Edit the last commit's message
git commit --amend --no-edit               # Add staged changes to last commit

git log                                     # Full commit history
git log --oneline                            # One line per commit
git log --oneline --graph --all               # Visual branch graph
git log -p -- file.txt                         # History of changes to one file
git log --author="name"                         # Filter by author
git blame file.txt                               # Who last changed each line


# =============================================================================
# 4. BRANCHING
# =============================================================================

git branch                          # List local branches
git branch -a                        # List local + remote branches
git branch new-branch                 # Create a branch (don't switch)
git checkout -b new-branch              # Create and switch to a branch
git switch -c new-branch                 # Same as above (modern syntax)
git switch branch-name                    # Switch to an existing branch
git checkout branch-name                   # Legacy switch syntax

git branch -d branch-name                   # Delete a merged local branch
git branch -D branch-name                    # Force-delete an unmerged branch
git push origin --delete branch-name          # Delete a remote branch

git branch -m old-name new-name                # Rename current or given branch


# =============================================================================
# 5. MERGING & REBASING
# =============================================================================

git merge branch-name                # Merge branch into current branch
git merge --no-ff branch-name          # Force a merge commit (no fast-forward)
git merge --abort                       # Abort a merge with conflicts

git rebase main                          # Replay current branch's commits onto main
git rebase -i HEAD~3                      # Interactive rebase: squash/reorder/edit last 3
git rebase --continue                      # Continue after resolving a conflict
git rebase --abort                          # Abort a rebase in progress

# Conflict resolution (either path):
#   1. Edit the conflicting file(s), remove <<<<<<< ======= >>>>>>> markers
#   2. git add <file>
#   3. git commit          (after merge)   OR   git rebase --continue (after rebase)

git cherry-pick <commit-hash>          # Apply a specific commit onto current branch


# =============================================================================
# 6. REMOTES
# =============================================================================

git remote -v                        # List remotes with URLs
git remote add origin <url>            # Add a remote named "origin"
git remote set-url origin <new-url>     # Change a remote's URL
git remote remove origin                 # Remove a remote

git fetch origin                          # Download remote refs, don't merge
git pull                                   # Fetch + merge current branch
git pull --rebase                           # Fetch + rebase instead of merge
git push                                     # Push current branch to its upstream
git push -u origin branch-name                # Push and set upstream tracking
git push --force-with-lease                    # Safer force-push (checks remote state)
git push --tags                                 # Push all local tags


# =============================================================================
# 7. UNDOING CHANGES
# =============================================================================

git restore file.txt                  # Discard unstaged changes to a file
git restore --staged file.txt           # Unstage a file (keep working changes)
git checkout -- file.txt                 # Legacy: discard unstaged changes

git reset --soft HEAD~1                    # Undo last commit, keep changes staged
git reset --mixed HEAD~1                    # Undo last commit, keep changes unstaged (default)
git reset --hard HEAD~1                      # Undo last commit, DISCARD all changes (destructive)

git revert <commit-hash>                      # Create a new commit that undoes a commit (safe for shared history)

git clean -fd                                  # Remove untracked files and dirs (destructive)
git clean -n                                    # Dry run — show what would be deleted


# =============================================================================
# 8. STASHING
# =============================================================================

git stash                            # Stash tracked changes
git stash -u                          # Stash tracked + untracked changes
git stash list                         # List all stashes
git stash pop                           # Apply and remove the latest stash
git stash apply stash@{0}                # Apply a specific stash, keep it in the list
git stash drop stash@{0}                  # Delete a specific stash
git stash show -p stash@{0}                # Show diff of a specific stash


# =============================================================================
# 9. TAGS & RELEASES
# =============================================================================

git tag                              # List tags
git tag v1.0.0                        # Create a lightweight tag
git tag -a v1.0.0 -m "Release 1.0.0"    # Create an annotated tag
git push origin v1.0.0                   # Push a single tag
git push origin --tags                    # Push all tags
git tag -d v1.0.0                          # Delete a local tag


# =============================================================================
# 10. INSPECTING & DEBUGGING
# =============================================================================

git show <commit-hash>                # Show a specific commit's changes
git show HEAD:file.txt                  # Show a file's content at HEAD
git reflog                               # History of HEAD movements (recover "lost" commits)
git bisect start                          # Binary search for the commit that introduced a bug
git bisect bad                             # Mark current commit as bad
git bisect good <commit-hash>                # Mark a known-good commit
git bisect reset                              # End the bisect session


# =============================================================================
# 11. .gitignore & UNTRACKING
# =============================================================================

# Add patterns to .gitignore, then stop tracking files that are already
# committed but should now be ignored:
git rm -r --cached path/to/dir        # Untrack a dir/file (keeps it on disk)
git rm -r --cached .                    # Untrack everything, then re-add per .gitignore
git add .
git commit -m "Apply .gitignore"

git check-ignore -v file.txt             # Debug why a file is/isn't ignored


# =============================================================================
# 12. GITHUB CLI (gh)
# =============================================================================

gh auth login                          # Authenticate the CLI
gh repo clone owner/repo                 # Clone via gh
gh repo create my-repo --public --source=. --push  # Create + push existing local repo
gh repo view --web                        # Open current repo in browser

gh pr create --title "Title" --body "Description"   # Open a pull request
gh pr create --fill                        # Auto-fill title/body from commits
gh pr list                                   # List open PRs
gh pr view 123 --web                          # Open PR #123 in browser
gh pr checkout 123                             # Check out a PR's branch locally
gh pr merge 123 --squash                        # Merge a PR (squash/merge/rebase)
gh pr diff 123                                   # Show a PR's diff
gh pr review 123 --approve                        # Approve a PR

gh issue create --title "Bug" --body "Details"      # Create an issue
gh issue list                                          # List issues
gh issue view 42                                        # View issue #42
gh issue close 42                                        # Close an issue

gh workflow list                                          # List GitHub Actions workflows
gh run list                                                 # List recent workflow runs
gh run watch                                                 # Watch the latest run live
gh run view <run-id> --log                                    # View a run's logs

gh release create v1.0.0 --notes "Release notes"                # Create a release
gh api repos/:owner/:repo/pulls/123/comments                      # Raw API access


# =============================================================================
# 13. COMMON WORKFLOWS
# =============================================================================

# --- Feature branch workflow ---
# git switch -c feature/my-feature
# ... make changes ...
# git add . && git commit -m "Add feature"
# git push -u origin feature/my-feature
# gh pr create --fill

# --- Keeping a feature branch up to date with main ---
# git fetch origin
# git rebase origin/main        (preferred for clean linear history)
#   or
# git merge origin/main          (preferred if branch is shared with others)

# --- Fixing the last commit before pushing ---
# git add forgotten_file.txt
# git commit --amend --no-edit

# --- Squashing the last N commits into one ---
# git rebase -i HEAD~N
#   mark all but the first commit as "squash" (or "s"), save, edit final message
