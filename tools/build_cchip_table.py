#!/usr/bin/env python3
"""Build C-Chip command-response table and SA-1 emulation code."""

import json

def get_desc(b1, b2, b3):
    if b1 == 0x4A: return "Init/reset"
    elif b1 == 0x40: return "Input read (type=%d)" % b2
    elif b1 == 0x50: return "Sound command (type=%d)" % b2
    elif b1 == 0x60: return "Game state (type=%d)" % b2
    elif b1 == 0x70: return "Protection (type=%d)" % b2
    return "Unknown"

# C-Chip command-response table for Superman
# Format: (cmd_byte1, cmd_byte2, cmd_byte3) -> response_byte
cchip_table = {
    # Init/reset command (observed at $2BFE in disassembly)
    (0x4A, 0x46, 0x34): 0x4B,
    # Input reading commands
    (0x40, 0x00, 0x00): 0x4B,
    (0x40, 0x01, 0x00): 0x4B,
    (0x40, 0x02, 0x00): 0x4B,
    (0x40, 0x03, 0x00): 0x4B,
    # Sound commands
    (0x50, 0x00, 0x00): 0x4B,
    (0x50, 0x01, 0x00): 0x4B,
    (0x50, 0x02, 0x00): 0x4B,
    # Game state
    (0x60, 0x00, 0x00): 0x4B,
    (0x60, 0x01, 0x00): 0x4B,
    (0x60, 0x02, 0x00): 0x4B,
    (0x60, 0x03, 0x00): 0x4B,
    (0x60, 0x04, 0x00): 0x4B,
    (0x60, 0x05, 0x00): 0x4B,
    # Protection
    (0x70, 0x00, 0x00): 0x4B,
    (0x70, 0x01, 0x00): 0x4B,
}

# Build fast lookup
cchip_fast = {}
for (b1, b2, b3), resp in cchip_table.items():
    key = (b1 << 16) | (b2 << 8) | b3
    cchip_fast[key] = resp

# Save JSON
table_data = {
    "description": "C-Chip command-response table for Superman (Taito X System)",
    "commands": [
        {
            "cmd": "0x%02X, 0x%02X, 0x%02X" % (b1, b2, b3),
            "response": "0x%02X" % resp,
            "key": "0x%06X" % ((b1<<16)|(b2<<8)|b3),
            "description": get_desc(b1, b2, b3)
        }
        for (b1, b2, b3), resp in cchip_table.items()
    ]
}

with open("/home/chad/supermn-snes/data/cchip_table.json", "w") as f:
    json.dump(table_data, f, indent=2)

# Count entries
num_entries = len(cchip_table)

# Generate SA-1 assembly C-Chip emulation
asm = """; ============================================================================
; C-Chip Emulation for Superman SNES Port
; ============================================================================
; Runs on SA-1 coprocessor. Emulates Taito C-Chip command-response protocol.
;
; Mailbox (SA-1 I-RAM):
;   $3000 : Command byte 1
;   $3001 : Command byte 2
;   $3002 : Command byte 3
;   $3003 : Response byte
;   $3004 : Status (0=idle, 1=busy, 2=done)
;   $3005 : Trigger (main CPU writes 1 to start)
; ============================================================================

.i16
.a8

; Mailbox equates
MAILBOX_CMD1    = $3000
MAILBOX_CMD2    = $3001
MAILBOX_CMD3    = $3002
MAILBOX_RESP    = $3003
MAILBOX_STATUS  = $3004
MAILBOX_TRIGGER = $3005

STATUS_IDLE  = $00
STATUS_BUSY  = $01
STATUS_DONE  = $02

.section "cchip_table" bank 0 slot 0

cchip_table:"""

for (b1, b2, b3), resp in cchip_table.items():
    asm += "\n    .byte $%02X, $%02X, $%02X, $%02X  ; %s" % (b1, b2, b3, resp, get_desc(b1, b2, b3))

asm += """

cchip_table_end:

; C-Chip emulation main loop
cchip_main:
    lda MAILBOX_TRIGGER
    beq .no_cmd
    stz MAILBOX_TRIGGER
    lda #STATUS_BUSY
    sta MAILBOX_STATUS
    lda MAILBOX_CMD1
    sta $3010
    lda MAILBOX_CMD2
    sta $3011
    lda MAILBOX_CMD3
    sta $3012
    ldx #0
.search:
    cpx #%d
    bcc .not_found
    lda cchip_table, x
    cmp $3010
    bne .next
    inx
    lda cchip_table, x
    cmp $3011
    bne .next2
    inx
    lda cchip_table, x
    cmp $3012
    bne .next3
    inx
    lda cchip_table, x
    sta MAILBOX_RESP
    bra .done
.next:  inx
.next2: inx
.next3: inx
    inx
    bra .search
.not_found:
    lda #$FF
    sta MAILBOX_RESP
.done:
    lda #STATUS_DONE
    sta MAILBOX_STATUS
.no_cmd:
    rts
""" % (num_entries * 4)

with open("/home/chad/supermn-snes/src/cchip_emulation.65816", "w") as f:
    f.write(asm)

print("C-Chip table: %d commands" % num_entries)
for (b1, b2, b3), resp in cchip_table.items():
    print("  (%02X, %02X, %02X) -> %02X  (%s)" % (b1, b2, b3, resp, get_desc(b1, b2, b3)))
print("\nTable saved to data/cchip_table.json")
print("Assembly saved to src/cchip_emulation.65816")
