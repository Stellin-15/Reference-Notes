# L03: Terminal Basics (for developers coming from Windows)

Mac's Terminal uses **zsh** by default (bash-like), not PowerShell or cmd.exe. Most Linux commands work as-is — this is a big advantage over Windows for dev work.

## Core commands (same as Linux)

```bash
ls          # list files (ls -la for hidden files + details)
cd          # change directory
pwd         # print working directory
mkdir       # make directory
rm          # remove file (rm -rf for folders — be careful, no recycle bin)
cp          # copy
mv          # move/rename
cat         # print file contents
grep        # search text
find        # find files
```

## Key differences from Windows

- Paths use `/` not `\`
- Home directory is `~` or `/Users/yourname`
- No drive letters (`C:\`) — everything is one filesystem tree starting at `/`
- Case-sensitive by default on newer setups (careful with filenames)

## Handy Mac-specific commands

```bash
open .              # opens the current folder in Finder
open somefile.txt   # opens a file with its default app
pbcopy < file.txt    # copy file contents to clipboard
pbpaste > file.txt   # paste clipboard contents into a file
```

## Install Homebrew first

Homebrew is the Mac equivalent of `apt`/`winget` — the standard way to install dev tools and apps from the terminal.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then:

```bash
brew install git node python        # command-line tools
brew install --cask visual-studio-code google-chrome  # GUI apps
brew list                            # see what's installed
brew upgrade                         # update everything
```

## Opening Terminal

- Spotlight (`Cmd+Space`) → type "Terminal" → Enter
- Or Launchpad → Other → Terminal
- Consider **iTerm2** (`brew install --cask iterm2`) later as a more powerful terminal replacement
