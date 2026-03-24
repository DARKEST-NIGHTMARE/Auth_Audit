#!/bin/bash
# Script to resolve backend/chroma_data conflicts and merge test into main

cd "/home/manmath/Documents/OAuth dummy/Login Auth Audit" || exit

echo "Aborting any stuck merge..."
git merge --abort || true

echo "Removing binary chroma_data from git index (files remain on disk)..."
git rm -r --cached backend/chroma_data/ || true

echo "Committing index fix..."
git commit -m "Stop tracking binary chroma_data database" || true

echo "Switching to main branch..."
git checkout main

echo "Merging test branch into main..."
git merge test --no-edit -m "Merge branch 'test' into main"

echo "Merge complete! You can safely delete this script."
