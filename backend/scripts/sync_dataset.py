import os
import shutil
import glob

# Paths
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(base_dir, "dataset", "new original datas for all the md files")
dest_dir = os.path.join(base_dir, "dataset")

print(f"Syncing dataset from {src_dir} to {dest_dir}")

# Find all md files recursively in src_dir
count = 0
for root, dirs, files in os.walk(src_dir):
    for file in files:
        if file.endswith(".md"):
            src_path = os.path.join(root, file)
            dest_path = os.path.join(dest_dir, file)
            
            # Copy file
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {file}")
            count += 1

print(f"Synced {count} markdown files successfully.")
