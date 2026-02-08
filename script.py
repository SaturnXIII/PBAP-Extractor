#!/usr/bin/env python3
"""
PBAP Extractor - Bluetooth Phone Book Access Profile Data Extraction Tool
Author: Athena
Version: 1.0.0
License: MIT

A professional tool for extracting contacts and call history from Bluetooth devices
via the PBAP (Phone Book Access Profile) protocol using obexctl.
"""

import pexpect
import sys
import time
import os
import shutil
import re
from pathlib import Path
import subprocess

# ANSI Color codes for terminal output
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'
    BG_BLUE = '\033[44m'

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

VERSION = "1.0.0"
TARGET_MAC = "" 
MAX_RETRIES = 3
CONSECUTIVE_FAILURES_LIMIT = 5  # Stop after 5 consecutive file not found
WORK_DIR = os.getcwd()
VCF_FOLDER = None

# ---------------------------------------------------------
# DISPLAY UTILITIES
# ---------------------------------------------------------

def print_banner():
    """Display application banner."""
    banner = f"""
{Colors.MAGENTA}{Colors.BOLD}
      ╔═══════════════════════════════════════╗
      ║    ( ( ( ) ) )                        ║
      ║   / \\_\\U_/ /\\                         ║
      ║  |  (o_o)  |  PBAP Extractor          ║
      ║  | /\\~_/\\ |  v{VERSION}                  ║
      ║  |_|  ~  |_|  by Athena               ║
      ╚═══════════════════════════════════════╝
{Colors.RESET}"""
    print(banner)

def print_header(title):
    """Display section header."""
    width = 70
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'═' * width}")
    print(f"  {title.upper()}")
    print(f"{'═' * width}{Colors.RESET}\n")

def print_status(icon, message, color=Colors.CYAN):
    """Display timestamped status message."""
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {color}{icon} {message}{Colors.RESET}")

def print_box(title, content, color=Colors.GREEN):
    """Display message in a formatted box."""
    width = 60
    print(f"\n{color}{Colors.BOLD}╔{'═' * (width-2)}╗")
    print(f"║ {title.center(width-4)} ║")
    print(f"╠{'═' * (width-2)}╣")
    for line in content:
        print(f"║ {line.ljust(width-4)} ║")
    print(f"╚{'═' * (width-2)}╝{Colors.RESET}\n")

# ---------------------------------------------------------
# BLUETOOTH SERVICE MANAGEMENT
# ---------------------------------------------------------

def check_bluetooth_service():
    """
    Verify that the Bluetooth service is active.
    Attempts to start it if inactive.
    """
    print_status("⚙", "Checking Bluetooth services...", Colors.CYAN)
    
    try:
        result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                              capture_output=True, text=True)
        if result.stdout.strip() != 'active':
            print_status("⚠", "Bluetooth service not active, attempting to start...", Colors.YELLOW)
            subprocess.run(['sudo', 'systemctl', 'start', 'bluetooth'], check=False)
            time.sleep(2)
        
        print_status("✓", "Bluetooth service is active", Colors.GREEN)
        return True
    except Exception as e:
        print_status("⚠", f"Cannot check Bluetooth service: {e}", Colors.YELLOW)
        return True  # Continue anyway

# ---------------------------------------------------------
# FOLDER MANAGEMENT
# ---------------------------------------------------------

def create_vcf_folder():
    """
    Create a timestamped folder for VCF file storage.
    Format: PBAP_YYYYMMDD_HHMMSS_MAC
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    mac_safe = TARGET_MAC.replace(':', '-')
    folder_name = f"PBAP_{timestamp}_{mac_safe}"
    folder_path = os.path.join(WORK_DIR, folder_name)
    
    try:
        os.makedirs(folder_path, exist_ok=True)
        print_status("📁", f"Created folder: {Colors.BOLD}{folder_name}{Colors.RESET}", Colors.GREEN)
        return folder_path
    except Exception as e:
        print_status("✗", f"Cannot create folder: {e}", Colors.RED)
        return None

# ---------------------------------------------------------
# FILE DETECTION & MANAGEMENT
# ---------------------------------------------------------

def find_downloaded_file(local_name, search_dirs, max_wait=4):
    """
    Search for a downloaded file in multiple possible locations.
    Waits up to max_wait seconds for the file to appear.
    
    Args:
        local_name: Filename to search for
        search_dirs: List of directories to check
        max_wait: Maximum wait time in seconds
    
    Returns:
        Full path to file if found, None otherwise
    """
    start_time = time.time()
    
    while (time.time() - start_time) < max_wait:
        for search_dir in search_dirs:
            possible_path = os.path.join(search_dir, local_name)
            
            if os.path.exists(possible_path):
                try:
                    size = os.path.getsize(possible_path)
                    if size > 0:
                        time.sleep(0.15)  # Wait for file write completion
                        return possible_path
                except:
                    pass
        
        time.sleep(0.3)
    
    return None

def move_to_vcf_folder(source_path, final_name):
    """
    Move a file to the VCF output folder.
    
    Args:
        source_path: Current file location
        final_name: Destination filename
    
    Returns:
        True if successful, False otherwise
    """
    try:
        dest_path = os.path.join(VCF_FOLDER, final_name)
        shutil.move(source_path, dest_path)
        return True
    except:
        return False

# ---------------------------------------------------------
# OBEX PROTOCOL INTERACTION
# ---------------------------------------------------------

def wait_transfer(child, timeout=10):
    """
    Wait for OBEX transfer completion.
    
    Args:
        child: pexpect spawn object
        timeout: Maximum wait time
    
    Returns:
        True if transfer successful, False otherwise
    """
    try:
        i = child.expect([
            r"Pull successful",
            r"Status: complete",
            r"Transfer complete",
            r"Failed",
            r"Error",
            pexpect.TIMEOUT
        ], timeout=timeout)
        
        return i <= 2
    except:
        return False

def download_with_smart_detection(child, base_path):
    """
    Download VCF files with intelligent failure detection.
    Stops after CONSECUTIVE_FAILURES_LIMIT consecutive file-not-found errors.
    
    Args:
        child: pexpect spawn object
        base_path: PBAP directory path ('pb' for contacts, 'ich' for call history)
    
    Returns:
        Number of successfully downloaded files
    """
    print_status("⚡", f"Starting extraction from /{base_path}", Colors.MAGENTA)
    print_status("⚙", f"Tolerance: {CONSECUTIVE_FAILURES_LIMIT} consecutive failures", Colors.CYAN)
    
    # Possible locations where obexctl might save files
    search_dirs = [
        os.path.expanduser("~"),
        os.getcwd(),
        "/tmp",
        os.path.join(os.path.expanduser("~"), "uio"),
        "/root",
    ]
    
    downloaded_count = 0
    index = 1
    consecutive_failures = 0
    total_checked = 0
    
    max_limit = 5000 if base_path == 'pb' else 300
    
    print()
    
    while index <= max_limit and consecutive_failures < CONSECUTIVE_FAILURES_LIMIT:
        source_file = f"{index}.vcf"
        local_name = f"tmp_{base_path}_{index}.vcf"
        
        # Generate final filename with zero-padding
        if base_path == 'pb':
            final_name = f"contact_{index:04d}.vcf"
        else:
            final_name = f"callhist_{index:04d}.vcf"
        
        # Request file via OBEX
        child.sendline(f"cp {source_file} {local_name}")
        
        # Wait for transfer
        wait_transfer(child, timeout=10)
        
        # Consume prompt
        try:
            child.expect("#", timeout=1)
        except:
            pass
        
        # Check if file actually exists
        time.sleep(0.2)
        file_path = find_downloaded_file(local_name, search_dirs, max_wait=4)
        
        total_checked += 1
        
        if file_path:
            if move_to_vcf_folder(file_path, final_name):
                downloaded_count += 1
                consecutive_failures = 0  # Reset counter on success
                
                ratio = f"{downloaded_count}/{total_checked}"
                print(f"\r{Colors.GREEN}✓ [{index:04d}] {final_name} {Colors.DIM}({ratio}){Colors.RESET}{' ' * 20}", end='')
                sys.stdout.flush()
            else:
                consecutive_failures += 1
        else:
            consecutive_failures += 1
            
            if consecutive_failures <= 3:
                print(f"\r{Colors.DIM}○ [{index:04d}] Not found (fail: {consecutive_failures}/{CONSECUTIVE_FAILURES_LIMIT}){' ' * 20}{Colors.RESET}", end='')
                sys.stdout.flush()
        
        index += 1
        time.sleep(0.1)
    
    print()
    
    if consecutive_failures >= CONSECUTIVE_FAILURES_LIMIT:
        print_status("◆", f"Auto-stop: {CONSECUTIVE_FAILURES_LIMIT} consecutive failures reached", Colors.YELLOW)
    
    if total_checked > 0:
        success_rate = (downloaded_count / total_checked) * 100
        print_status("ℹ", f"Success rate: {downloaded_count}/{total_checked} ({success_rate:.1f}%)", Colors.CYAN)
    
    return downloaded_count

def connect_and_extract(target_path):
    """
    Establish OBEX connection and extract data from specified path.
    
    Args:
        target_path: PBAP directory ('pb' for contacts, 'ich' for call history)
    
    Returns:
        True if extraction successful, False otherwise
    """
    print_header(f"Extracting {target_path.upper()} directory")
    
    # Brief pause to ensure services are ready
    time.sleep(1)
    
    print_status("→", "Starting obexctl...", Colors.CYAN)
    
    child = pexpect.spawn("obexctl", encoding="utf-8", timeout=15, cwd=WORK_DIR)

    try:
        # Wait for initial prompt
        child.expect("#", timeout=5)
        
        print_status("→", f"Connecting to {Colors.BOLD}{TARGET_MAC}{Colors.RESET}...", Colors.CYAN)
        child.sendline(f"connect {TARGET_MAC} pbap")
        
        # Wait for connection response
        i = child.expect([
            "Connection successful",
            "Client proxy not available",
            "Failed",
            pexpect.TIMEOUT
        ], timeout=20)
        
        if i == 1:
            # OBEX client not ready - wait and retry
            print_status("⚠", "OBEX client not ready, waiting 3s...", Colors.YELLOW)
            child.sendline("quit")
            child.close()
            time.sleep(3)
            return False
        
        if i != 0:
            print_status("✗", "Connection failed", Colors.RED)
            child.sendline("quit")
            child.close()
            return False
        
        print_status("✓", "Connected successfully", Colors.GREEN)
        child.expect("#", timeout=3)
        
        # Navigate to target directory
        print_status("→", f"Accessing /{target_path}...", Colors.CYAN)
        child.sendline(f"cd {target_path}")
        
        i = child.expect(["Select successful", "Failed", "#"], timeout=5)
        if i == 1:
            print_status("✗", f"Cannot access /{target_path}", Colors.RED)
            child.sendline("quit")
            child.close()
            return False
        
        child.expect("#", timeout=3)
        print_status("✓", "Directory accessed", Colors.GREEN)

        # Download files
        file_count = download_with_smart_detection(child, target_path)
        
        # Disconnect
        child.sendline("quit")
        try:
            child.expect(pexpect.EOF, timeout=2)
        except:
            pass
        child.close()
        
        if file_count > 0:
            print_status("✓", f"{Colors.BOLD}{file_count}{Colors.RESET} files downloaded", Colors.GREEN)
            return True
        else:
            print_status("⚠", "No files downloaded", Colors.YELLOW)
            return False
        
    except Exception as e:
        print_status("✗", f"Error: {e}", Colors.RED)
        try:
            child.sendline("quit")
            child.close(force=True)
        except:
            pass
        return False

# ---------------------------------------------------------
# VCF PARSING
# ---------------------------------------------------------

def parse_vcf(vcf_content):
    """
    Parse VCF file content and extract contact information.
    
    Args:
        vcf_content: Raw VCF file content
    
    Returns:
        Dictionary containing parsed contact data
    """
    data = {}
    
    # Parse name (FN or N field)
    fn = re.search(r"FN:([^\n\r]+)", vcf_content, re.I)
    if fn:
        data['Name'] = fn.group(1).strip()
    else:
        n_match = re.search(r"N:([^;\n\r]*);([^;\n\r]*);", vcf_content, re.I)
        if n_match:
            first = n_match.group(2).strip()
            last = n_match.group(1).strip()
            data['Name'] = f"{first} {last}".strip() or "UNKNOWN"
        else:
            data['Name'] = "UNKNOWN"
    
    # Parse phone numbers
    tel_matches = re.findall(r"TEL(?:;([^:]*))?: ?([^\n\r]+)", vcf_content, re.I)
    phones = []
    for type_info, number in tel_matches:
        clean_num = number.strip().replace('-', '').replace(' ', '')
        phones.append(clean_num)
    data['Phones'] = phones
    
    # Parse emails
    data['Emails'] = re.findall(r"EMAIL(?:;[^:]*)*:([^\n\r]+)", vcf_content, re.I)
    
    # Parse organization
    org = re.search(r"ORG:([^\n\r]+)", vcf_content, re.I)
    if org:
        data['Organization'] = org.group(1).strip()
    
    # Parse call history specific fields
    ct = re.search(r"X-BT-CALL-TYPE:([^\n\r]+)", vcf_content, re.I)
    if ct:
        data['CallType'] = ct.group(1).strip()
    
    cd = re.search(r"X-BT-CALL-DATE:([^\n\r]+)", vcf_content, re.I)
    if cd:
        data['CallDate'] = cd.group(1).strip()
    
    return data

def generate_summary():
    """
    Generate a text summary report from all extracted VCF files.
    
    Returns:
        True if summary generated successfully, False otherwise
    """
    output_file = os.path.join(VCF_FOLDER, "EXTRACTION_SUMMARY.txt")
    
    vcf_files = sorted([
        f for f in os.listdir(VCF_FOLDER) 
        if f.endswith(".vcf") and (f.startswith("contact_") or f.startswith("callhist_"))
    ])

    if not vcf_files:
        return False

    print_header("Generating Summary Report")
    print_status("📝", f"Processing {len(vcf_files)} VCF files...", Colors.CYAN)
    
    contact_count = 0
    call_count = 0
    
    with open(output_file, "w", encoding="utf-8") as out:
        # Write header
        out.write("=" * 80 + "\n")
        out.write("PBAP EXTRACTION SUMMARY REPORT\n")
        out.write("=" * 80 + "\n")
        out.write(f"Date & Time    : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"Target Device  : {TARGET_MAC}\n")
        out.write(f"Total Files    : {len(vcf_files)}\n")
        out.write(f"Output Folder  : {VCF_FOLDER}\n")
        out.write("=" * 80 + "\n\n")
        
        # Process each VCF file
        for vcf in vcf_files:
            is_contact = vcf.startswith("contact_")
            
            if is_contact:
                contact_count += 1
                header = f"CONTACT #{contact_count}"
            else:
                call_count += 1
                header = f"CALL HISTORY #{call_count}"
            
            try:
                with open(os.path.join(VCF_FOLDER, vcf), "r", encoding="utf-8", errors='ignore') as f:
                    content = f.read()
                
                data = parse_vcf(content)
                
                out.write("─" * 80 + "\n")
                out.write(f"  {header} - {vcf}\n")
                out.write("─" * 80 + "\n")
                
                # Call history specific fields
                if 'CallType' in data:
                    out.write(f"  Call Type      : {data['CallType']}\n")
                    out.write(f"  Call Date/Time : {data.get('CallDate', 'N/A')}\n")
                    out.write("\n")
                
                # Common fields
                out.write(f"  Name           : {data['Name']}\n")
                
                if data['Phones']:
                    out.write(f"  Phone(s)       : {', '.join(data['Phones'])}\n")
                
                if data['Emails']:
                    out.write(f"  Email(s)       : {', '.join(data['Emails'])}\n")
                
                if 'Organization' in data:
                    out.write(f"  Organization   : {data['Organization']}\n")
                
                out.write("\n")
                
            except:
                continue
        
        # Write footer
        out.write("=" * 80 + "\n")
        out.write(f"SUMMARY: {contact_count} Contacts | {call_count} Call History Entries\n")
        out.write("=" * 80 + "\n")

    print_status("✓", "Summary report created", Colors.GREEN)
    
    stats = [
        f"Total VCF Files: {len(vcf_files)}",
        f"Contacts: {contact_count}",
        f"Call History: {call_count}",
        f"Location: {os.path.basename(VCF_FOLDER)}",
    ]
    
    print_box("EXTRACTION STATISTICS", stats, Colors.GREEN)
    
    return True

# ---------------------------------------------------------
# MAIN PROGRAM
# ---------------------------------------------------------

def validate_mac(mac_address):
    """Validate MAC address format."""
    return re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac_address, re.I)

def main():
    """Main program entry point."""
    global TARGET_MAC, VCF_FOLDER
    
    os.system('clear')
    print_banner()
    
    info = [
        f"Working Directory: {WORK_DIR}",
        f"Failure Tolerance: {CONSECUTIVE_FAILURES_LIMIT} consecutive failures",
        f"Max Retries: {MAX_RETRIES}",
    ]
    print_box("CONFIGURATION", info, Colors.CYAN)
    
    # Check Bluetooth service
    check_bluetooth_service()
    
    # Get target MAC address
    while True:
        TARGET_MAC = input(f"\n{Colors.BLUE}{Colors.BOLD}Enter Target MAC Address: {Colors.RESET}").strip().upper()
        
        if validate_mac(TARGET_MAC):
            TARGET_MAC = TARGET_MAC.replace('-', ':')
            break
        else:
            print_status("✗", "Invalid MAC format (use XX:XX:XX:XX:XX:XX)", Colors.RED)
    
    print_status("✓", f"Target: {Colors.BOLD}{TARGET_MAC}{Colors.RESET}", Colors.GREEN)
    
    # Create output folder
    VCF_FOLDER = create_vcf_folder()
    if not VCF_FOLDER:
        sys.exit(1)
    
    success_contacts = False
    success_calls = False
    
    # Extraction loop with retries
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n{Colors.BG_BLUE}{Colors.BOLD} ATTEMPT {attempt}/{MAX_RETRIES} {Colors.RESET}\n")
        
        # Extract contacts
        if not success_contacts:
            success_contacts = connect_and_extract("pb")
        
        # Extract call history
        if not success_calls:
            success_calls = connect_and_extract("ich")
        
        # Check if extraction succeeded
        if success_contacts or success_calls:
            if generate_summary():
                result = [
                    "✓ Extraction completed successfully",
                    f"✓ Files saved in: {os.path.basename(VCF_FOLDER)}",
                ]
                print_box("SUCCESS", result, Colors.GREEN)
                sys.exit(0)
        
        # Wait before retry
        if attempt < MAX_RETRIES:
            print_status("⟳", "Retrying in 3 seconds...", Colors.YELLOW)
            time.sleep(3)
    
    # All attempts failed
    print_box("EXTRACTION FAILED", [f"Failed after {MAX_RETRIES} attempts"], Colors.RED)
    sys.exit(1)

if __name__ == "__main__":
    main()
