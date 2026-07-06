# ============================================================
# L03: File Systems Internals
# ============================================================
# WHAT: How an operating system actually stores and retrieves files on
#       disk — inodes, directory structures as simple name-to-inode
#       mappings, and journaling as the mechanism that protects against
#       corruption from a mid-write crash or power loss.
# WHY: This repo's Bash & Scripting Notes and DevOps & SRE Practices
#      Notes both treat "the filesystem" as a given interface (ls, cp,
#      mv) without covering how it actually works underneath — this
#      lesson opens that abstraction.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
AN INODE is the fundamental data structure most Unix-like filesystems
(ext4, and similar concepts elsewhere) use to represent a FILE'S
METADATA and the LOCATIONS of its actual DATA BLOCKS on disk —
critically, an inode does NOT store the file's NAME at all — it stores
things like file size, permissions, timestamps, ownership, and pointers
to the actual disk blocks containing the file's content. This
separation of "file identity/metadata" (the inode) from "file name" is
the foundation for several filesystem behaviors that otherwise seem
surprising.

A DIRECTORY IS SIMPLY A SPECIAL FILE containing a MAPPING FROM NAMES TO
INODE NUMBERS — when you run `ls`, you're reading a directory's list of
(filename, inode number) pairs; when you open a file by path, the OS
walks this mapping to find the corresponding inode, then uses the
inode's block pointers to locate the actual data. This explains HARD
LINKS directly: a hard link is simply ANOTHER directory entry (another
name) pointing to the SAME inode — the file's data isn't duplicated,
and the file only ACTUALLY disappears from disk once its LINK COUNT
(tracked in the inode) drops to zero (i.e., no more directory entries
reference it) — this is why deleting a file that still has another hard
link doesn't free its disk space; the data is still reachable via the other name.

A SYMBOLIC LINK (symlink), by contrast, is a genuinely DIFFERENT
mechanism: it's a small special file whose CONTENT is simply the TEXT
PATH of the target file — following a symlink means the OS reads this
path text and then looks UP that path fresh, which means a symlink can
point to files on a DIFFERENT filesystem/partition entirely (unlike a
hard link, which requires the same filesystem, since inode numbers are
only meaningful WITHIN a single filesystem), and a symlink becomes
"broken" (dangling) if its target is deleted or moved, since it's just
storing a path string with no inherent connection to the target's actual inode.

JOURNALING is the mechanism modern filesystems (ext4, NTFS, and others)
use to protect against corruption from a crash or power loss occurring
MID-WRITE: rather than writing changes DIRECTLY to their final on-disk
location (where a crash halfway through could leave the filesystem
structure in an inconsistent, corrupted state), the filesystem first
writes a description of the intended changes to a separate JOURNAL (a
dedicated log area) — only once this journal entry is safely written
does the filesystem apply the actual changes to their final location.
If a crash occurs mid-write, the filesystem can REPLAY the journal on
next boot to either COMPLETE or CLEANLY ROLL BACK the interrupted
operation, avoiding the kind of structural corruption (lost files, a
filesystem the OS can't even properly mount) that could occur without this safeguard.

PRODUCTION USE CASE:
A backup script creates a hard link to a large file rather than copying
it, when it needs the file to appear in TWO different directory
locations without doubling disk usage — since a hard link is just
another name pointing to the SAME inode/data blocks, this achieves
"the file exists in two places" with ZERO additional storage cost,
unlike an actual copy — a technique commonly used by backup tools
(like `rsync --link-dest`) specifically to create space-efficient
incremental backups that still appear as complete, independent snapshots.

COMMON MISTAKES:
- Assuming deleting a file immediately frees its disk space — if the
  file has additional HARD LINKS (other names pointing to the same
  inode) or is still held open by a running process, the underlying
  data remains until the link count AND open file handle count both reach zero.
- Confusing hard links and symbolic links' capabilities — attempting to
  hard-link a file across DIFFERENT filesystems/partitions will fail
  (inode numbers aren't portable across filesystems), while a symlink
  can point anywhere, including across filesystems, since it's just storing a path string.
- Assuming a filesystem operation is atomic/instantaneous without
  understanding journaling's role — while journaling makes the
  FILESYSTEM STRUCTURE crash-safe, it does NOT necessarily guarantee
  your specific APPLICATION-level data write (e.g. writing a large file
  in multiple chunks) is atomic from the application's own perspective
  — application-level atomicity (e.g. write-to-temp-then-rename patterns)
  is a separate consideration layered on top of filesystem-level safety.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Inodes and directory entries, illustrated conceptually
# ------------------------------------------------------------------
class Inode:
    def __init__(self, inode_number: int, size: int, data_blocks: list[int]):
        self.inode_number = inode_number
        self.size = size
        self.data_blocks = data_blocks
        self.link_count = 0   # incremented for EACH directory entry pointing here


class SimpleFilesystem:
    def __init__(self):
        self.inodes: dict[int, Inode] = {}
        self.directory: dict[str, int] = {}   # filename -> inode_number
        self.next_inode_number = 1

    def create_file(self, filename: str, size: int, data_blocks: list[int]):
        inode = Inode(self.next_inode_number, size, data_blocks)
        inode.link_count = 1
        self.inodes[inode.inode_number] = inode
        self.directory[filename] = inode.inode_number
        self.next_inode_number += 1

    def create_hard_link(self, existing_filename: str, new_filename: str):
        inode_number = self.directory[existing_filename]
        self.directory[new_filename] = inode_number
        self.inodes[inode_number].link_count += 1

    def delete_file(self, filename: str):
        inode_number = self.directory.pop(filename)
        inode = self.inodes[inode_number]
        inode.link_count -= 1
        if inode.link_count == 0:
            print(f"    Link count reached 0 — inode {inode_number}'s "
                  f"data blocks {inode.data_blocks} are NOW actually freed")
            del self.inodes[inode_number]
        else:
            print(f"    Link count now {inode.link_count} — data blocks "
                  f"{inode.data_blocks} remain allocated (still reachable via another name)")


def hard_link_demo():
    fs = SimpleFilesystem()
    fs.create_file("document.txt", size=4096, data_blocks=[101, 102])
    print(f"Created 'document.txt' -> inode {fs.directory['document.txt']}, "
          f"link_count={fs.inodes[fs.directory['document.txt']].link_count}")

    fs.create_hard_link("document.txt", "backup/document_copy.txt")
    inode_num = fs.directory["document.txt"]
    print(f"After hard-linking to 'backup/document_copy.txt': "
          f"link_count={fs.inodes[inode_num].link_count}")
    print("  -> BOTH names point to the SAME inode/data blocks — no data was duplicated.\n")

    print("Deleting 'document.txt':")
    fs.delete_file("document.txt")
    print(f"  'backup/document_copy.txt' still works: "
          f"{'backup/document_copy.txt' in fs.directory}")

    print("\nDeleting 'backup/document_copy.txt' too:")
    fs.delete_file("backup/document_copy.txt")


if __name__ == "__main__":
    hard_link_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A daily backup tool creates incremental backups using hard links: each
day's backup directory contains hard links to UNCHANGED files from the
previous day's backup (sharing the same inode, zero extra disk space)
and only actually stores NEW data for files that changed — this lets
each day's backup directory appear to be a COMPLETE, independent
snapshot (you can browse "yesterday's backup" as if it's a full copy)
while the ACTUAL disk usage only reflects the files that genuinely
changed between backups — a direct, practical application of
understanding that a hard link is a NAME pointing to shared data, not a duplicate copy.
"""
