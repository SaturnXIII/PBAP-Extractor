# PBAP-Extractor (Bluetooth Phonebook Access)

**A Pentesting Tool for Bluetooth PBAP and ICH Data Extraction**

By Athena

` ( ( ( ) ) )`  <br>
` / \_\U_/ /\ ` <br>
`|  (o_o)  |  PBAP Extractor `<br>
`| /\~_/\\ |  v5.0 `<br>
`|_|  ~  |_|  by Athena `<br>


---

## 💡 Overview

This Python script is designed for **authorized penetration testing** of Bluetooth devices. It uses `obexctl` to automatically pull, parse, and merge contact lists (`/pb`) and call logs (`/ich`) via PBAP access into a single text file.

It uses `obexctl` to manage the Bluetooth connection and features built-in logic to handle file conflicts and organize the extracted VCF data.

## ⚠️ Ethical & Legal Disclaimer

**USE THIS TOOL RESPONSIBLY AND ONLY ON SYSTEMS YOU OWN OR HAVE EXPLICIT, WRITTEN PERMISSION TO TEST.** The author is not responsible for any unauthorized or illegal misuse.

---

## 🚀 Usage

1.  **Requirements:** Linux, Python 3, `pexpect` (`pip install pexpect`), and `obexctl`.
2.  **Run:** Execute with `sudo python3 script.py`.
3.  **Input:** The script will prompt for the **target MAC address**.

###### put to good use #####
╭∩╮(-_-)╭∩╮
######
