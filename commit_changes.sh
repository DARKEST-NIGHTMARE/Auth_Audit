#!/bin/bash
# Script to stage and commit remaining unstaged local changes

cd "/home/manmath/Documents/OAuth dummy/Login Auth Audit" || exit

echo "Current Unstaged Changes:"
git status -s

echo ""
echo "Adding all files..."
git add .

echo "Committing..."
git commit -m "Commit unstaged modularization and RAG updates post-merge"

echo ""
echo "Final Git Status:"
git status
