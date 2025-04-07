#!/usr/bin/env python3
"""
Script to fix multiline f-strings in Python files for compatibility with Python 3.11.

This script scans all Python files in a directory recursively, identifies multiline
f-strings with the pattern f"...{...newline...}..." and fixes them by reformatting
to a single line.
"""

import os
import re
import sys
import argparse
from pathlib import Path


def fix_multiline_fstrings(content):
    """
    Fix multiline f-strings in the given content.
    
    Args:
        content (str): The Python file content to fix
        
    Returns:
        str: The fixed content
        bool: Whether any changes were made
    """
    # Pattern to match f-strings where the expression crosses a line boundary
    # This includes raw f-strings (rf"...") and any quote style
    pattern = r'((?:r?f|f)(?:["\']).*?\{)(\s*?\n\s*?)(.*?\}.*?(?:["\']))'
    
    # Track if any replacements were made
    made_changes = False
    
    # Function to replace with a single line
    def replace_match(match):
        nonlocal made_changes
        made_changes = True
        start = match.group(1)
        end = match.group(3)
        # Replace the newline and extra whitespace with a single space
        return f"{start}{end}"
    
    # Apply the fix repeatedly until no more changes (to handle nested cases)
    prev_content = None
    while prev_content != content:
        prev_content = content
        content = re.sub(pattern, replace_match, content, flags=re.DOTALL)
    
    # Handle more complex patterns where a new line might be in the middle of the expression
    # For cases like f"text { something \n more_stuff } text"
    complex_pattern = r'((?:r?f|f)(?:["\']).*?\{[^}]*?)(\n\s*?)([^{]*?\}.*?(?:["\']))'
    
    # Apply the complex fix repeatedly
    prev_content = None
    while prev_content != content:
        prev_content = content
        content = re.sub(complex_pattern, replace_match, content, flags=re.DOTALL)
    
    return content, made_changes


def process_file(file_path, no_backup=False):
    """
    Process a single Python file to fix multiline f-strings.
    
    Args:
        file_path (str): Path to the Python file to process
        no_backup (bool): If True, don't create backup files
        
    Returns:
        bool: Whether any changes were made
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        fixed_content, made_changes = fix_multiline_fstrings(content)
        
        if made_changes:
            # Create a backup before modifying if needed
            if not no_backup:
                backup_path = f"{file_path}.bak"
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            # Write the fixed content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            
            print(f"✅ Fixed multiline f-strings in {file_path}")
            return True
        
        return False
    
    except Exception as e:
        print(f"❌ Error processing {file_path}: {str(e)}")
        return False


def find_python_files(directory):
    """
    Find all Python files in the given directory recursively.
    
    Args:
        directory (str): Directory to search for Python files
        
    Returns:
        list: List of paths to Python files
    """
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files


def main():
    """Main function to process all Python files in a directory."""
    parser = argparse.ArgumentParser(
        description='Fix multiline f-strings in Python files for compatibility '
                    'with Python 3.11'
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='Directory to scan for Python files (default: current directory)'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Do not create backup files'
    )
    parser.add_argument(
        '--include',
        type=str,
        help='Only process files matching this pattern (e.g., "*/util.py")'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Do not modify files, just show what would be changed'
    )
    
    args = parser.parse_args()
    directory = args.directory
    
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory")
        return 1
    
    print(f"Scanning {directory} for Python files...")
    python_files = find_python_files(directory)
    
    # Apply include filter if specified
    if args.include:
        import fnmatch
        python_files = [f for f in python_files if fnmatch.fnmatch(f, args.include)]
    
    print(f"Found {len(python_files)} Python files to process")
    
    fixed_count = 0
    for file_path in python_files:
        if args.dry_run:
            # In dry run, just check if changes would be made
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            fixed_content, would_change = fix_multiline_fstrings(content)
            if would_change:
                print(f"🔍 Would fix multiline f-strings in {file_path}")
                fixed_count += 1
        else:
            # Actually process the file
            if process_file(file_path, args.no_backup):
                fixed_count += 1
    
    if args.dry_run:
        print(f"\n✨ Summary: Would fix {fixed_count} files out of {len(python_files)}")
    else:
        print(f"\n✨ Summary: Fixed {fixed_count} files out of {len(python_files)}")
        
        if fixed_count > 0 and not args.no_backup:
            print("\nBackup files were created with .bak extension.")
            print("You can delete them once you've verified the changes:")
            print(f"find {directory} -name '*.py.bak' -delete")
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 