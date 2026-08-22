# SPDX-License-Identifier: MIT
"""Business profile engine — personal vs commercial deployment.

Commercial mode: the user selects an industry (15 built-in types or a custom
one), optionally uploads SOP handbooks / ISO documents, and the platform
generates a professional company instruction prompt with AI.  That prompt is
injected into EVERY chat, and an industry-specific enterprise workspace
(ISO 9001 / 14001 / 45001 / 25001-aligned registers, logs and KPIs) is
activated in the menu."""
from __future__ import annotations

import json

# ============================================================
# Industry templates — each defines the enterprise modules
# (registers/logs) of the workspace with their fields, and the
# ISO clauses each module supports.
# field types: text | number | date | select:opt1,opt2 | textarea
# ============================================================
INDUSTRY_TEMPLATES: dict[str, dict] = {
    "retail": {"label": "Retail", "icon": "🏪", "modules": [
        {"key": "returns", "name": "Returns / RMA Register", "iso": "9001 §8.7·10.2",
         "fields": [["rma", "RMA #", "text"], ["receipt", "Receipt / Order #", "text"],
                    ["sku", "SKU", "text"], ["reason", "Reason", "text"],
                    ["at", "Date", "date"],
                    ["status", "Status", "select:requested,approved,received,refunded,exchanged,rejected"]]},
        {"key": "shrink", "name": "Shrink / Loss Prevention Log", "iso": "9001 §9.1",
         "fields": [["at", "Date", "date"], ["dept", "Department", "text"],
                    ["type", "Type", "select:damage,theft,expiry,admin error"],
                    ["value", "Value $", "number"], ["note", "Note", "textarea"]]},
        {"key": "planogram", "name": "Merchandising / Planogram Checklist", "iso": "9001 §8.5.1",
         "fields": [["area", "Area / Aisle", "text"], ["task", "Task", "text"],
                    ["due", "Due", "date"], ["owner", "Owner", "text"],
                    ["status", "Status", "select:planned,in progress,done"]]},
    ]},
    "restaurant": {"label": "Restaurant", "icon": "🍽️", "modules": [
        {"key": "haccp_temp", "name": "HACCP Temperature Log", "iso": "9001·22000",
         "fields": [["unit", "Unit / Fridge", "text"], ["temp_c", "Temp °C", "number"],
                    ["checked_by", "Checked by", "text"], ["at", "Date", "date"],
                    ["corrective", "Corrective action", "textarea"]]},
        {"key": "food_safety", "name": "Food Safety Incident Register", "iso": "9001 §10.2",
         "fields": [["at", "Date", "date"], ["desc", "Incident", "textarea"],
                    ["severity", "Severity", "select:low,medium,high,critical"],
                    ["root_cause", "Root cause", "textarea"], ["capa", "Corrective/Preventive action", "textarea"]]},
        {"key": "supplier", "name": "Approved Supplier Register", "iso": "9001 §8.4",
         "fields": [["name", "Supplier", "text"], ["category", "Category", "text"],
                    ["cert", "Certifications", "text"], ["rating", "Rating", "select:A,B,C"],
                    ["review", "Next review", "date"]]},
        {"key": "cleaning", "name": "Cleaning & Sanitation Schedule", "iso": "14001 §8.1",
         "fields": [["area", "Area", "text"], ["task", "Task", "text"],
                    ["freq", "Frequency", "select:daily,weekly,monthly"],
                    ["done_by", "Done by", "text"], ["at", "Date", "date"]]},
        {"key": "waste", "name": "Waste & Oil Disposal Log", "iso": "14001 §8.1",
         "fields": [["at", "Date", "date"], ["type", "Waste type", "select:organic,oil,packaging,glass,hazardous"],
                    ["qty", "Quantity (kg/L)", "number"], ["carrier", "Disposal carrier", "text"]]},
    ]},
    "insurance": {"label": "Insurance Agent", "icon": "🛡️", "modules": [
        {"key": "policies", "name": "Policy Register", "iso": "9001 §8.2",
         "fields": [["client", "Client", "text"], ["carrier", "Carrier", "text"],
                    ["type", "Line", "select:auto,home,life,health,commercial,umbrella"],
                    ["premium", "Premium $", "number"], ["renewal", "Renewal date", "date"],
                    ["status", "Status", "select:quoted,bound,active,lapsed,cancelled"]]},
        {"key": "claims", "name": "Claims Tracker", "iso": "9001 §8.7·10.2",
         "fields": [["client", "Client", "text"], ["claim_no", "Claim #", "text"],
                    ["at", "Loss date", "date"], ["desc", "Description", "textarea"],
                    ["status", "Status", "select:filed,adjusting,approved,denied,paid"]]},
        {"key": "eo_compliance", "name": "E&O / License Compliance", "iso": "9001 §7.2",
         "fields": [["item", "Item", "text"], ["expiry", "Expiry", "date"],
                    ["state", "State/Region", "text"], ["status", "Status", "select:valid,renewal due,expired"]]},
        {"key": "leads", "name": "Lead & Referral Pipeline", "iso": "9001 §8.2.1",
         "fields": [["name", "Prospect", "text"], ["source", "Source", "text"],
                    ["line", "Interest", "text"], ["stage", "Stage", "select:new,contacted,quoted,won,lost"],
                    ["follow", "Follow-up", "date"]]},
    ]},
    "realtor": {"label": "Realtor", "icon": "🏠", "modules": [
        {"key": "listings", "name": "Listing Register", "iso": "9001 §8.2",
         "fields": [["addr", "Property address", "text"], ["price", "List price $", "number"],
                    ["mls", "MLS #", "text"], ["status", "Status", "select:coming soon,active,pending,sold,withdrawn"],
                    ["expiry", "Listing expiry", "date"]]},
        {"key": "escrow", "name": "Escrow / Transaction Checklist", "iso": "9001 §8.5.1",
         "fields": [["addr", "Property", "text"], ["milestone", "Milestone", "select:offer,inspection,appraisal,loan,contingency removal,closing"],
                    ["due", "Due date", "date"], ["owner", "Responsible", "text"],
                    ["done", "Complete", "select:no,yes"]]},
        {"key": "clients", "name": "Client & Showing Log", "iso": "9001 §8.2.1",
         "fields": [["name", "Client", "text"], ["type", "Type", "select:buyer,seller,tenant,landlord"],
                    ["at", "Showing date", "date"], ["property", "Property", "text"], ["feedback", "Feedback", "textarea"]]},
        {"key": "disclosures", "name": "Disclosure & Document Register", "iso": "9001 §7.5",
         "fields": [["addr", "Property", "text"], ["doc", "Document", "text"],
                    ["signed", "Signed date", "date"], ["status", "Status", "select:pending,signed,filed"]]},
    ]},
    "warehouse": {"label": "Warehouse", "icon": "🏭", "modules": [
        {"key": "inbound", "name": "Inbound Receiving Register", "iso": "9001 §8.5.4·8.6",
         "fields": [["asn", "ASN / PO #", "text"], ["supplier", "Supplier / Shipper", "text"],
                    ["carrier", "Carrier", "text"], ["at", "Received", "date"],
                    ["items", "Items / SKUs", "textarea"], ["qty", "Qty", "number"],
                    ["dock", "Dock / Door", "text"],
                    ["status", "Status", "select:scheduled,arrived,unloading,inspected,putaway,discrepancy"]]},
        {"key": "outbound", "name": "Outbound Shipment Register", "iso": "9001 §8.5.4·8.5.1",
         "fields": [["shipment", "Shipment #", "text"], ["customer", "Customer / Consignee", "text"],
                    ["carrier", "Carrier", "text"], ["at", "Ship date", "date"],
                    ["items", "Items / SKUs", "textarea"], ["qty", "Qty", "number"],
                    ["bol", "BOL / Tracking #", "text"],
                    ["status", "Status", "select:planned,picking,packed,staged,shipped,delivered"]]},
        {"key": "cycle_counts", "name": "Cycle Count / Stock Accuracy Log", "iso": "9001 §8.5.4·9.1",
         "fields": [["at", "Date", "date"], ["location", "Location / Bin", "text"],
                    ["sku", "SKU", "text"], ["expected", "System qty", "number"],
                    ["counted", "Counted qty", "number"], ["variance", "Variance", "number"],
                    ["action", "Adjustment / action", "textarea"]]},
    ]},
    "fulfillment": {"label": "Fulfillment Center", "icon": "📦", "modules": [
        {"key": "inbound", "name": "Inbound Receiving Register", "iso": "9001 §8.5.4·8.6",
         "fields": [["asn", "ASN / PO #", "text"], ["client", "Client / Merchant", "text"],
                    ["carrier", "Carrier", "text"], ["at", "Received", "date"],
                    ["items", "Items / SKUs", "textarea"], ["qty", "Qty", "number"],
                    ["status", "Status", "select:scheduled,arrived,inspected,putaway,discrepancy"]]},
        {"key": "outbound", "name": "Outbound Order Fulfillment", "iso": "9001 §8.5.1·8.5.4",
         "fields": [["order", "Order #", "text"], ["client", "Client / Merchant", "text"],
                    ["carrier", "Carrier / Service", "text"], ["at", "Ship date", "date"],
                    ["tracking", "Tracking #", "text"],
                    ["sla", "SLA met", "select:yes,no"],
                    ["status", "Status", "select:received,picking,packed,shipped,delivered,exception"]]},
        {"key": "exceptions", "name": "Order Exception Register", "iso": "9001 §8.7·10.2",
         "fields": [["order", "Order #", "text"], ["at", "Date", "date"],
                    ["issue", "Issue", "select:short pick,damaged,mis-ship,address,carrier delay,lost"],
                    ["resolution", "Resolution", "textarea"],
                    ["status", "Status", "select:open,resolved,credited,reshipped"]]},
    ]},
    "contractor": {"label": "Contractor / Service Shop", "icon": "🔨", "modules": [
        {"key": "service", "name": "Service Job / Work Order Board", "iso": "9001 §8.5",
         "fields": [["job", "Job / WO #", "text"], ["customer", "Customer", "text"],
                    ["site", "Site / Address", "text"], ["scope", "Scope of work", "textarea"],
                    ["tech", "Technician / Crew", "text"], ["at", "Scheduled", "date"],
                    ["amount", "Quoted $", "number"],
                    ["status", "Status", "select:estimate,approved,scheduled,in progress,awaiting parts,completed,invoiced"]]},
        {"key": "warranty", "name": "Warranty / Callback Register", "iso": "9001 §8.7·10.2",
         "fields": [["job", "Original Job #", "text"], ["customer", "Customer", "text"],
                    ["at", "Reported", "date"], ["issue", "Issue", "textarea"],
                    ["status", "Status", "select:reported,scheduled,reworked,closed"]]},
        {"key": "permits", "name": "Permit & Inspection Register", "iso": "9001 §8.5.3·45001 §8.1",
         "fields": [["job", "Job #", "text"], ["permit", "Permit / Inspection", "text"],
                    ["agency", "Agency", "text"], ["due", "Due / Scheduled", "date"],
                    ["status", "Status", "select:applied,issued,inspection passed,failed,closed"]]},
    ]},
    "recycle": {"label": "Refurbished / Recycle", "icon": "♻️", "modules": [
        # ===== Aligned to the company IMS (MFI-001 Master Form Index) =====
        # A. Receiving — FRM-REC-001/002/003/004
        {"grp": "A · RECEIVING", "icon": "📥", "key": "inbound", "name": "Incoming Equipment Receiving (FRM-REC-001)", "iso": "14001 §8.1·9001 §8.6·R2 Core 6",
         "fields": [["lot", "Lot No. assigned", "text"], ["at", "Receiving date", "date"],
                    ["source", "Supplier / Customer", "text"], ["carrier", "Carrier", "text"],
                    ["po", "PO / Ref No.", "text"],
                    ["equipment", "Equipment type(s)", "textarea"],
                    ["pallets", "Total pallets / boxes", "number"],
                    ["weight", "Gross weight (kg)", "number"],
                    ["data_bearing", "Data-bearing media suspected", "select:no,yes — to Data Security (FRM-HDD-SEC-001)"],
                    ["fm", "Focus materials present", "select:none,batteries,CRT,LCD-Hg,PCB,solar,multiple"],
                    ["condition", "Load secure / undamaged", "select:yes,no — damage report (FRM-REC-003)"],
                    ["routing", "Routing", "select:to Asset Control (FRM-AST-INV-001),to Dismantling,to FM Storage (FRM-R2-FM-001),to Data Security (FRM-HDD-SEC-001)"],
                    ["status", "Status", "select:received,verified,routed,discrepancy"]]},
        # B. Asset Control — FRM-AST-INV-001/002/003/004
        {"grp": "B · ASSET CONTROL", "icon": "🏷️", "key": "wh_inbound", "name": "Asset Registration & Inventory (FRM-AST-INV-001)", "iso": "9001 §8.5.4·R2 Core 5",
         "fields": [["asset_id", "Asset ID assigned", "text"], ["lot", "Lot No.", "text"],
                    ["at", "Registration date", "date"], ["by", "Registered by", "text"],
                    ["equipment", "Equipment type", "text"], ["model", "Make / Model", "text"],
                    ["serial", "Serial No.", "text"],
                    ["grade", "Condition grade", "select:A,B,C,scrap"],
                    ["data_bearing", "Data-bearing media", "select:no,yes — logged to FRM-HDD-SEC-001"],
                    ["location", "Storage location", "text"],
                    ["label", "Label applied (FRM-AST-INV-002)", "select:yes,pending"],
                    ["status", "Status", "select:registered,in storage,moved,adjusted,shipped"]]},
        # C. Chromebook Testing & Repair — FRM-CHR-TEST-001…005
        #    Stage 1 of the two-stage QC process: receiving → pre-cleaning
        #    inspection → functional testing → repair → sanitization → cleaning.
        #    The official Final QC (FRM-QC-001) is performed AFTER cleaning.
        {"grp": "C · TESTING & REPAIR", "icon": "💻", "key": "qc", "name": "Chromebook Testing & Repair (FRM-CHR-TEST-001)", "iso": "9001 §8.6·R2 App. C",
         "fields": [["sku", "SKU", "text"], ["serial", "Serial No.", "text"],
                    ["lot", "Asset / Lot", "text"], ["model", "Model", "text"],
                    ["tech", "Technician", "text"], ["at", "Test date", "date"],
                    ["safety", "Pre-test safety (ESD, battery, wiring, liquid)", "select:pass,not pass — quarantine"],
                    ["precheck", "Pre-cleaning inspection (existing damage)", "checks:scratches,cracks,missing parts,stickers,battery swelling,liquid damage,none"],
                    ["precheck_notes", "Pre-cleaning damage notes / photo refs", "textarea"],
                    ["reset", "Reset method", "select:powerwash,developer,n/a"],
                    ["aue", "AUE status", "select:supported,near expiry,expired"],
                    ["tests", "Functional test checklist", "checks:keyboard,touchpad,display,audio,camera,Wi-Fi,USB ports,battery & charging,webcam privacy switch,hinges & chassis,speakers,microphone"],
                    ["result", "Overall result", "select:pass,repair needed,not pass,no power / dead"],
                    ["repairs", "Repairs performed / parts", "textarea"],
                    ["wipe", "Data sanitization completed (WIPE-004)", "select:pass,pending,n/a"],
                    ["lock", "Enterprise enrollment / lock check", "select:not locked,locked — to Spare Parts (FRM-SPARE-001),pending"],
                    ["disposition", "Unit disposition", "select:continue to cleaning & Final QC,to Spare Parts — locked unit (FRM-SPARE-001),to Spare Parts — no power / not functional (FRM-SPARE-001),to Disposal Area — recycle process (FRM-RCY-001)"],
                    ["spare_loc", "Spare Parts / Disposal location (map code)", "text"],
                    ["cleaned", "Cleaning & cosmetic prep completed", "select:pending,done — to Final QC (FRM-QC-001),n/a — routed to spare parts / disposal"],
                    ["cleaner", "Cleaned by", "text"],
                    ["cosmetic", "Cosmetic grade (FRM-CHR-TEST-004)", "select:A,B,C,D"],
                    ["status", "Status", "select:testing,burn-in,repaired,sanitizing,cleaning,awaiting final QC,released,to spare parts,to disposal,rejected"]]},
        # C2. Spare Parts Harvesting — FRM-SPARE-001 (locked / no-power / not-
        #     functional units routed for part harvesting; when fully harvested
        #     and non-functional → transfer to Disposal Area → FRM-RCY-001)
        {"grp": "C · TESTING & REPAIR", "icon": "🧰", "key": "spare_parts", "name": "Spare Parts Harvest & Usage (FRM-SPARE-001)", "iso": "9001 §8.5.4·R2 App. C·Core 5",
         "fields": [["asset_id", "Asset ID / Serial", "text"], ["lot", "Lot No.", "text"],
                    ["model", "Model", "text"], ["at", "Date received", "date"],
                    ["reason", "Reason routed to spare parts", "select:enterprise-locked,no power / dead,not functional — uneconomic repair,cosmetic donor,other"],
                    ["wipe", "Data-bearing media removed / sanitized (FRM-HDD-SEC-001)", "select:verified,n/a — no media,pending — hold"],
                    ["location", "Spare Parts location (map code)", "text"],
                    ["by", "Logged by", "text"],
                    ["parts_used", "Parts harvested (screen, keyboard, battery, mainboard, hinges, etc.)", "textarea"],
                    ["remaining", "Usable parts remaining", "select:yes — keep in spare parts,no — fully harvested"],
                    ["transfer", "Carcass transfer", "select:n/a — still in use,to Disposal Area — recycle process (FRM-RCY-001)"],
                    ["transfer_ref", "Recycle intake ref (FRM-RCY-001)", "text"],
                    ["status", "Status", "select:in spare parts storage,partially harvested,fully harvested,transferred to disposal,closed"]]},
        # C3. Reuse Evaluation & Categorization — R2v3 Core 6 + App. C
        {"grp": "C · TESTING & REPAIR", "icon": "🔍", "key": "reuse_eval", "name": "Reuse Evaluation & Categorization (FRM-REU-001)", "iso": "R2 Core 6·App. C",
         "fields": [["lot", "Lot / asset refs", "text"], ["at", "Evaluated", "date"],
                    ["category", "R2 reuse category", "select:full functions tested,key functions tested — defects disclosed,evaluated — not tested (downstream verification required),non-reusable → recycle (FRM-RCY-001)"],
                    ["test_plan", "Test plan ref (FRM-CHR-TEST-001)", "text"],
                    ["label", "Category label applied to unit / lot", "select:yes,pending"],
                    ["disclosure", "Defects / grade disclosed to buyer", "select:yes,n/a,pending"],
                    ["by", "Evaluated by", "text"],
                    ["status", "Status", "select:pending,categorized,shipped,closed"]]},
        # C4. Brand Protection & Counterfeit Control — R2 REC / trademark law
        {"grp": "C · TESTING & REPAIR", "icon": "🏷️", "key": "brand_protect", "name": "Brand Protection & Counterfeit Control (FRM-REU-002)", "iso": "R2 REC·9001 §8.4",
         "fields": [["item", "Item / lot", "text"], ["at", "Checked", "date"],
                    ["authentic", "Trademark / authenticity verified", "select:genuine,suspect counterfeit — quarantine,OEM authorization on file"],
                    ["evidence", "Evidence (serials, holograms, OEM confirmation)", "textarea"],
                    ["action", "Action on counterfeit", "select:n/a,quarantined,destroyed / recycled with evidence,reported to brand owner / authority"],
                    ["by", "Checked by", "text"],
                    ["status", "Status", "select:cleared,quarantined,destroyed,reported,closed"]]},
        # J. Quality — FRM-QC-001 Final QC (Stage 2 — performed AFTER cleaning;
        #    independent inspector: not the person who repaired or cleaned)
        {"grp": "J · QUALITY (ISO 9001)", "icon": "✅", "key": "refurb", "name": "Final QC Inspection & Release — post-cleaning (FRM-QC-001)", "iso": "9001 §8.6·R2 App. C",
         "fields": [["lot", "Lot / Asset IDs", "text"], ["at", "Inspection date", "date"],
                    ["inspector", "Inspector (must differ from repair/cleaning tech)", "text"],
                    ["independent", "Independent of repair & cleaning", "select:yes,no — staffing exception logged"],
                    ["sample", "Sample size / 100%", "text"],
                    ["functional", "All functional tests passed (screen, keyboard, touchpad, camera, Wi-Fi, USB, charging, speakers, mic)", "select:pass,fail"],
                    ["wipe_verified", "Data sanitization completed & documented (WIPE-004)", "select:pass,fail,n/a"],
                    ["lock_verified", "Not enterprise-locked (verified)", "select:pass,fail"],
                    ["battery", "Battery condition meets acceptance standard", "select:pass,fail"],
                    ["clean", "Clean, dry, no residue / streaks / new damage from cleaning", "select:pass,fail"],
                    ["cosmetic", "Cosmetic grade correct", "select:pass,fail"],
                    ["identity", "Serial & asset info match records", "select:pass,fail"],
                    ["accessories", "Charger & accessories correct", "select:pass,fail,n/a"],
                    ["labelling", "QC label / inspector approval attached", "select:pass,fail"],
                    ["decision", "Decision", "select:release,reject — NC report (FRM-QC-002),return to cleaning,return to repair"],
                    ["approved_by", "Approved by", "text"],
                    ["status", "Status", "select:pending,released,rejected,returned"]]},
        # J2. Nonconforming Output Control — 9001 §8.7 (FRM-QC-002 — referenced
        #     by Final QC and Receiving; controls quarantine & disposition)
        {"grp": "J · QUALITY (ISO 9001)", "icon": "🚫", "key": "nonconforming", "name": "Nonconforming Output Control (FRM-QC-002)", "iso": "9001 §8.7·R2 Core 5",
         "fields": [["nc_no", "NC report No.", "text"], ["at", "Raised", "date"],
                    ["source", "Detected at", "select:receiving inspection,testing & repair,final QC,customer return,internal audit,warehouse inspection"],
                    ["item", "Item / lot / asset refs", "text"],
                    ["desc", "Nonconformity description", "textarea"],
                    ["quarantine", "Quarantined / segregated (location map code)", "text"],
                    ["disposition", "Disposition", "select:rework / repair,regrade,to spare parts (FRM-SPARE-001),to recycle process (FRM-RCY-001),return to supplier,scrap / disposal"],
                    ["concession", "Concession / customer approval required", "select:no,yes — obtained,yes — pending"],
                    ["capa", "CAPA raised (systemic cause)", "select:no — isolated,yes — ref FRM-QC-004"],
                    ["verified_by", "Disposition verified by", "text"],
                    ["status", "Status", "select:open,quarantined,disposition done,verified,closed"]]},
        # J3. Returns / RMA & Post-Delivery — 9001 §8.5.5 · §8.7 · R2 Core 7
        {"grp": "J · QUALITY (ISO 9001)", "icon": "📥", "key": "returns_rma", "name": "Returns / RMA & Post-Delivery (FRM-QC-003)", "iso": "9001 §8.5.5·R2 Core 7",
         "fields": [["rma", "RMA No.", "text"], ["at", "Received", "date"],
                    ["customer", "Customer", "text"], ["item", "Asset ID / order ref", "text"],
                    ["reason", "Return reason", "select:functional failure,cosmetic,wrong item,customer remorse,warranty claim,other"],
                    ["data_check", "Data-bearing check on return (customer data may be present)", "select:no media,media present — secured (FRM-HDD-SEC-001),pending — hold"],
                    ["quarantine", "Quarantined at (map code)", "text"],
                    ["disposition", "Disposition", "select:repair & return,replace,refund,re-test & restock,to spare parts,to recycle (FRM-RCY-001)"],
                    ["root_cause", "Root cause / CAPA (if systemic)", "text"],
                    ["by", "Processed by", "text"],
                    ["status", "Status", "select:received,quarantined,dispositioned,closed"]]},
        # D. Desktop Dismantling — FRM-DTK-DIS-001…004
        {"grp": "D · DISMANTLING", "icon": "🔩", "key": "dismantling", "name": "Desktop Dismantling Record (FRM-DTK-DIS-001)", "iso": "14001 §8.1·R2 Core 6",
         "fields": [["lot", "Lot No.", "text"], ["at", "Date", "date"],
                    ["assets", "Asset IDs / Qty units", "text"], ["tech", "Technician", "text"],
                    ["hdd", "HDD/SSD removed → FRM-HDD-SEC-001 (qty)", "number"],
                    ["batteries", "Batteries removed → OP-001 (qty)", "number"],
                    ["pcb", "PCBs / motherboards (qty)", "number"],
                    ["materials", "Other streams (PSU, RAM/CPU, cables kg, steel kg, plastics kg)", "textarea"],
                    ["media_secured", "All data media removed & secured", "select:yes,no — stop"],
                    ["segregation", "Segregation done (FRM-DTK-DIS-002)", "select:yes,pending"],
                    ["status", "Status", "select:in progress,completed,verified"]]},
        # E. Data Security — FRM-HDD-SEC-001…004
        {"grp": "E · DATA SECURITY", "icon": "🔒", "key": "media_security", "name": "Data-Bearing Media Security Log (FRM-HDD-SEC-001)", "iso": "R2 Core 7·27001 §A.7.14",
         "fields": [["serial", "Media serial No.", "text"],
                    ["type", "Media type", "select:HDD,SSD,eMMC / flash,tape,phone / tablet,other"],
                    ["source", "Source asset / lot", "text"], ["at", "Date in", "date"],
                    ["by", "Logged by", "text"], ["bin", "Secure storage bin", "text"],
                    ["locked", "Locked area confirmed — no power-on / read", "select:confirmed,violation — investigate (FRM-HDD-SEC-004)"],
                    ["date_out", "Date out (transfer)", "date"],
                    ["transfer_ref", "Transfer ref (FRM-DATA-WIPE-001)", "text"],
                    ["status", "Status", "select:in secure storage,staged for transfer,transferred,reconciled,missing — investigation"]]},
        # E2. Data Security Area — physical access control (R2 Core 7)
        {"grp": "E · DATA SECURITY", "icon": "🔐", "key": "secure_access", "name": "Secure Area Access & Security Check (FRM-HDD-SEC-002)", "iso": "R2 Core 7·27001 §A.7.2",
         "fields": [["at", "Date", "date"], ["kind", "Entry kind", "select:authorized staff,escorted visitor / contractor,security inspection,camera / lock check,key / badge audit"],
                    ["person", "Person", "text"], ["escort", "Escort (visitors)", "text"],
                    ["purpose", "Purpose", "text"],
                    ["time_in", "Time in", "text"], ["time_out", "Time out", "text"],
                    ["locks", "Locks / cage / cameras functional", "select:yes,no — incident raised (FRM-HDD-SEC-004)"],
                    ["inventory_ok", "Spot inventory reconciles (FRM-HDD-SEC-001)", "select:yes,discrepancy — investigation,n/a"],
                    ["status", "Status", "select:logged,exception — investigating,closed"]]},
        # F. Outsourced Data Sanitization — FRM-DATA-WIPE-001…006 (vendor: E-Waste Security)
        {"grp": "F · DATA SANITIZATION", "icon": "🧹", "key": "data_sanitize", "name": "Outsourced Data Sanitization (FRM-DATA-WIPE-001)", "iso": "R2 App. B·NIST 800-88",
         "fields": [["lot", "Lot No.", "text"], ["at", "Transfer date", "date"],
                    ["coordinator", "Internal coordinator", "text"],
                    ["vendor", "Vendor (approved)", "select:E-Waste Security — Fountain Valley CA,other approved vendor"],
                    ["qty", "Total media qty (HDD / SSD / other)", "number"],
                    ["manifest", "Manifest ref (FRM-DATA-WIPE-003)", "text"],
                    ["seals", "Tamper-evident seal No(s).", "text"],
                    ["coc", "Chain of custody opened (FRM-DATA-WIPE-002)", "select:yes,no — hold"],
                    ["cert", "Vendor certificate No. (FRM-DATA-WIPE-004)", "text"],
                    ["verified_by", "Certificate verified by", "text"],
                    ["status", "Status", "select:preparing,released to vendor,at vendor,certificate received,verified & reconciled,exception (FRM-DATA-WIPE-005)"]]},
        # F2. Sanitization Verification Sampling — R2v3 App. B(5): independent QC
        #     verification of sanitized media on a sampling basis.
        {"grp": "F · DATA SANITIZATION", "icon": "🧪", "key": "sanitize_verify", "name": "Sanitization Verification Sampling (FRM-DATA-WIPE-006)", "iso": "R2 App. B(5)·NIST 800-88",
         "fields": [["batch", "Sanitization batch / cert ref", "text"], ["at", "Verified", "date"],
                    ["sample_n", "Sample size (units)", "number"], ["batch_n", "Batch size (units)", "number"],
                    ["method", "Verify method", "select:full read-back verify,forensic spot-check (hex sectors),vendor tool verify log,hidden-area check (HPA/DCO)"],
                    ["verifier", "Verified by (must differ from sanitizer)", "text"],
                    ["independent", "Independent of sanitization operator", "select:yes,no — invalid, reassign"],
                    ["failures", "Failures found (qty)", "number"],
                    ["action", "On failure", "select:n/a — all passed,100% re-verify batch + re-sanitize,quarantine batch — NC (FRM-QC-002)"],
                    ["status", "Status", "select:pending,passed,failed — re-processing,closed"]]},
        # G. R2 Focus Material Management — FRM-R2-FM-001…008
        {"grp": "G · FOCUS MATERIALS (R2)", "icon": "🔋", "key": "focus_materials", "name": "Focus Material Inventory (FRM-R2-FM-001)", "iso": "14001 §8.1·R2 Core 8",
         "fields": [["at", "Date", "date"],
                    ["material", "FM type", "select:batteries,CRT glass,mercury / LCD-Hg,PCB,solar panels / PV,other"],
                    ["qty_in", "In (kg / qty)", "number"], ["qty_out", "Out (kg / qty)", "number"],
                    ["balance", "Balance on site", "number"],
                    ["location", "Container / Location", "text"],
                    ["inspection", "Storage inspection done (FM-002…006)", "select:yes,due,overdue"],
                    ["age_check", "≤180-day storage limit checked", "select:yes,exceeded — expedite shipment"],
                    ["shipment_ref", "Shipment ref (FRM-R2-FM-007)", "text"],
                    ["status", "Status", "select:in storage,staged,shipped,closed"]]},
        # App A/B — Downstream vendors (Hoi Tong International, E-Waste Security)
        {"grp": "G · FOCUS MATERIALS (R2)", "icon": "🔗", "key": "downstream", "name": "Downstream Vendor Tracking (FRM-R2-FM-008)", "iso": "R2 App. A·Core 5",
         "fields": [["vendor", "Downstream vendor", "text"],
                    ["record", "Vendor record ref (DV-001 Hoi Tong / DV-002 E-Waste Security / …)", "text"],
                    ["material", "Material streams sent", "textarea"],
                    ["certs", "Certifications (R2 / e-Stewards / ISO)", "text"],
                    ["audit_at", "Last due-diligence review", "date"],
                    ["next_audit", "Next review due", "date"],
                    ["fm_accepted", "Accepts focus materials", "select:no,yes — documented"],
                    ["status", "Status", "select:approved,conditional,suspended,terminated"]]},
        # M. Recycle Process — FRM-RCY-001/002/003 (ISO 14001 §8.1 · 45001 §8.1
        #    · 9001 §8.5 · R2v3 Core 5/6/8/10). Intake from Disposal Area →
        #    segregation → storage (no downstream yet) or outbound (downstream
        #    approved per FRM-R2-FM-008 due diligence).
        {"grp": "M · RECYCLE PROCESS (R2)", "icon": "♻️", "key": "recycle_intake", "name": "Recycle Process Intake & Segregation (FRM-RCY-001)", "iso": "14001 §8.1·45001 §8.1·R2 Core 6",
         "fields": [["intake", "Intake No. assigned", "text"], ["at", "Intake date", "date"],
                    ["source", "Source", "select:Disposal Area — spare parts carcasses (FRM-SPARE-001),Final QC reject (FRM-QC-002),dismantling residue (FRM-DTK-DIS-001),receiving — direct scrap (FRM-REC-001),other internal"],
                    ["source_ref", "Source record ref", "text"],
                    ["by", "Processed by", "text"],
                    ["desc", "Units / materials description", "textarea"],
                    ["qty", "Qty / Weight (kg)", "number"],
                    ["media_check", "Data-bearing media verification — none present or removed (FRM-HDD-SEC-001)", "select:verified clear,media found — quarantined to Data Security,pending — hold"],
                    ["fm_check", "Focus materials segregated (batteries, LCD-Hg, PCB → FRM-R2-FM-001)", "select:done,none present,pending — hold"],
                    ["ppe", "PPE & safe handling per JHA (gloves, eye protection, battery kit) — 45001 §8.1", "select:confirmed,deviation — incident report (FRM-SAF-006)"],
                    ["streams", "Material streams (steel, aluminium, plastics, PCB, cables, screens, mixed e-scrap)", "textarea"],
                    ["routing", "Routing", "select:to Recycle Storage — no downstream assigned (map code),to Downstream Outbound (FRM-RCY-003),to Focus Material Storage (FRM-R2-FM-001)"],
                    ["location", "Recycle Storage location (map code)", "text"],
                    ["status", "Status", "select:intake,segregated,in recycle storage,staged for outbound,shipped,closed"]]},
        {"grp": "M · RECYCLE PROCESS (R2)", "icon": "🏪", "key": "recycle_storage", "name": "Recycle Storage Inventory & Inspection (FRM-RCY-002)", "iso": "14001 §8.1·45001 §8.1·R2 Core 8/9",
         "fields": [["at", "Date", "date"], ["by", "Inspector", "text"],
                    ["location", "Recycle Storage location (map code)", "text"],
                    ["stream", "Material stream", "select:mixed e-scrap,steel,aluminium,plastics,PCB / boards,cables,screens / panels,spare-part carcasses"],
                    ["balance", "Balance on hand (kg / qty)", "number"],
                    ["containers", "Containers labelled, closed & undamaged", "select:yes,no — corrective action"],
                    ["weather", "Protected from weather / leaks — 14001 §8.1", "select:yes,no — corrective action"],
                    ["stacking", "Safe stacking height & aisle clearance — 45001 §8.1", "select:yes,no — corrective action"],
                    ["age_check", "Storage age within limit (≤180 days R2 target)", "select:yes,approaching limit — assign downstream,exceeded — escalate to management"],
                    ["downstream_status", "Downstream assignment", "select:not assigned — sourcing in progress,assigned — staged for FRM-RCY-003"],
                    ["action", "Corrective action (if any)", "textarea"],
                    ["status", "Status", "select:in storage,staged,shipped,closed"]]},
        {"grp": "M · RECYCLE PROCESS (R2)", "icon": "📤", "key": "recycle_outbound", "name": "Downstream Outbound Shipment (FRM-RCY-003)", "iso": "9001 §8.5.1·R2 Core 10·App. A",
         "fields": [["shipment", "Shipment No.", "text"], ["at", "Ship date", "date"],
                    ["vendor", "Downstream vendor (approved per FRM-R2-FM-008)", "text"],
                    ["vendor_verified", "Vendor due diligence current (R2 App. A audit valid)", "select:verified,expired — hold shipment"],
                    ["streams", "Material streams & lot / intake refs (FRM-RCY-001)", "textarea"],
                    ["qty", "Qty / Weight (kg)", "number"],
                    ["fm", "Focus materials included", "select:none,yes — FM manifest attached (FRM-R2-FM-007)"],
                    ["export", "Transboundary / export legality verified (importing-country consent, Basel)", "select:n/a — domestic,verified legal,pending — hold shipment"],
                    ["packing", "Packing & load securement checklist", "select:done,pending"],
                    ["docs", "Docs complete (manifest / BOL / DG declaration)", "select:yes,no — hold"],
                    ["carrier", "Carrier / Vehicle / Seal No.", "text"],
                    ["released_by", "Released by", "text"],
                    ["cert", "Downstream receipt / certificate No.", "text"],
                    ["status", "Status", "select:planned,staged,released,in transit,delivered,certificate received,reconciled,closed"]]},
        # I. Shipping — FRM-SHP-001…004
        {"grp": "I · SHIPPING", "icon": "🚚", "key": "outbound", "name": "Shipment Record (FRM-SHP-001)", "iso": "9001 §8.5.1·R2 Core 10",
         "fields": [["shipment", "Shipment No.", "text"], ["at", "Ship date", "date"],
                    ["dest", "Customer / Vendor & destination", "text"],
                    ["carrier", "Carrier / Vehicle / Seal No.", "text"],
                    ["contents", "Description & lot / asset refs", "textarea"],
                    ["qty", "Qty / Weight", "number"],
                    ["packing", "Packing checklist (FRM-SHP-002)", "select:done,pending"],
                    ["inspection", "Outgoing inspection (FRM-SHP-003)", "select:pass,pending,fail"],
                    ["export", "Export legality (R2 App. C — destination accepts used equipment)", "select:n/a — domestic,verified legal,pending — hold"],
                    ["docs", "Docs complete (invoice / manifest / DG)", "select:yes,no — hold"],
                    ["released_by", "Released by / Carrier signature (FRM-SHP-004)", "text"],
                    ["status", "Status", "select:planned,loaded,released,in transit,delivered,closed"]]},
        # H. Warehouse — FRM-WHS-001…006
        {"grp": "H · WAREHOUSE", "icon": "🏭", "key": "warehouse_inspection", "name": "Warehouse Daily Inspection (FRM-WHS-001)", "iso": "45001 §8.1·R2 Core 9",
         "fields": [["at", "Date", "date"], ["inspector", "Inspector", "text"],
                    ["aisles", "Aisles / exits clear", "select:yes,no"],
                    ["floors", "Floors clean & dry", "select:yes,no"],
                    ["containers", "Containers labelled & closed", "select:yes,no"],
                    ["leaks", "No leaks / odours", "select:yes,no"],
                    ["equipment", "Trolleys / pallet jacks OK", "select:yes,no"],
                    ["fire", "Fire extinguishers unobstructed", "select:yes,no"],
                    ["cleanup", "End-of-shift clean-up done (OP-007)", "select:yes,no"],
                    ["result", "All OK", "select:yes,no — action required"],
                    ["action", "Action taken if not OK", "textarea"]]},
        # K. Environmental — FRM-ENV-001…007
        {"grp": "K · ENVIRONMENTAL (ISO 14001)", "icon": "☣️", "key": "waste_disposal", "name": "Waste & Hazardous Disposal (FRM-ENV-002/003)", "iso": "14001 §8.1",
         "fields": [["at", "Date", "date"],
                    ["type", "Waste type", "select:general,non-recyclable,hazardous (FRM-ENV-003),universal,chemical"],
                    ["desc", "Description", "text"], ["qty", "Qty / Weight (kg)", "number"],
                    ["hauler", "Hauler", "text"], ["dest", "Destination facility", "text"],
                    ["manifest", "Manifest / Receipt No.", "text"],
                    ["status", "Status", "select:staged,shipped,receipt received,closed"]]},
        {"grp": "K · ENVIRONMENTAL (ISO 14001)", "icon": "🌡️", "key": "env_monitoring", "name": "Environmental Monitoring (FRM-ENV-006/007)", "iso": "14001 §6.1.2·9.1.1",
         "fields": [["at", "Date", "date"],
                    ["aspect", "Aspect monitored", "select:air / dust,noise,storm water,spill containment,storage integrity,energy use,objective KPI (FRM-ENV-007)"],
                    ["result", "Reading / result", "text"],
                    ["limit", "Limit / target", "text"],
                    ["compliant", "Within limit", "select:yes,no — action required"],
                    ["action", "Action taken", "textarea"]]},
        # L. Safety — FRM-SAF-001…010
        {"grp": "L · SAFETY (ISO 45001)", "icon": "🦺", "key": "ehs_incidents", "name": "Safety Incident & Near-Miss (FRM-SAF-006/007)", "iso": "45001 §10.2·R2 Core 3",
         "fields": [["at", "Date / Time", "date"], ["location", "Location", "text"],
                    ["worker", "Person(s) involved", "text"], ["witnesses", "Witnesses", "text"],
                    ["type", "Type", "select:near miss (FRM-SAF-007),first aid (FRM-SAF-005),injury,chemical / FM exposure,spill (FRM-ENV-005),fire,property damage"],
                    ["desc", "Description of event", "textarea"],
                    ["root_cause", "Root cause (5-Why)", "textarea"],
                    ["capa", "Corrective actions (CAR ref FRM-QC-004)", "textarea"],
                    ["risk_updated", "Risk assessment updated (FRM-SAF-002)", "select:yes,pending"],
                    ["reported", "Reported to authority", "select:n/a,yes,no"],
                    ["status", "Status", "select:open,investigating,action taken,closed"]]},
        # Core 2 / Core 4 — legal & permits
        {"grp": "K · ENVIRONMENTAL (ISO 14001)", "icon": "📜", "key": "env_permits", "name": "Permit, License & Legal Register", "iso": "14001 §6.1.3·R2 Core 4",
         "fields": [["permit", "Permit / License (incl. R2 cert, EPA Handler ID CAR000388173)", "text"],
                    ["agency", "Agency / CB", "text"],
                    ["scope", "Scope / conditions", "textarea"],
                    ["expiry", "Expiry / surveillance date", "date"],
                    ["status", "Status", "select:valid,renewal due,expired,suspended"]]},
        # K2. Environmental Aspects & Impacts — 14001 §6.1.2 (auditors always ask)
        {"grp": "K · ENVIRONMENTAL (ISO 14001)", "icon": "🌍", "key": "env_aspects", "name": "Environmental Aspects & Impacts Register (FRM-ENV-001)", "iso": "14001 §6.1.2",
         "fields": [["activity", "Activity / process", "text"],
                    ["aspect", "Environmental aspect", "select:dust / particulate,noise,energy use,waste generation,hazardous material storage,storm water runoff,spill potential,transport emissions,focus material handling"],
                    ["impact", "Impact", "textarea"],
                    ["condition", "Condition", "select:normal,abnormal,emergency"],
                    ["severity", "Severity 1-5", "number"], ["likelihood", "Likelihood 1-5", "number"],
                    ["significant", "Significant aspect", "select:yes — controls required,no"],
                    ["controls", "Operational controls (SOP / permit / containment)", "textarea"],
                    ["review", "Next review", "date"],
                    ["status", "Status", "select:current,review due,superseded"]]},
        # K3. Compliance Obligations Evaluation — 14001/45001 §9.1.2
        {"grp": "K · ENVIRONMENTAL (ISO 14001)", "icon": "⚖️", "key": "legal_eval", "name": "Compliance Obligations Evaluation (FRM-ENV-004)", "iso": "14001 §9.1.2·45001 §9.1.2·R2 Core 4",
         "fields": [["at", "Evaluation date", "date"], ["by", "Evaluated by", "text"],
                    ["obligation", "Legal / other requirement (statute, permit condition, R2 code)", "textarea"],
                    ["applicability", "Applies to", "text"],
                    ["compliant", "Compliance status", "select:compliant,minor gap — action plan,non-compliant — CAPA raised (FRM-QC-004)"],
                    ["evidence", "Evidence reviewed", "textarea"],
                    ["next", "Next evaluation due", "date"],
                    ["status", "Status", "select:evaluated,action open,closed"]]},
        # L2. Hazard Identification & Risk Assessment — 45001 §6.1.2.1
        {"grp": "L · SAFETY (ISO 45001)", "icon": "⚠️", "key": "hazard_ja", "name": "Hazard Identification & JHA (FRM-SAF-002)", "iso": "45001 §6.1.2·R2 Core 3",
         "fields": [["task", "Task / process step", "text"],
                    ["hazard", "Hazard", "select:battery fire / thermal runaway,cuts / sharps,ergonomic / lifting,electrical shock,chemical / FM exposure,forklift / traffic,dust,noise,slips & trips,pinch / crush,other"],
                    ["severity", "Severity 1-5", "number"], ["likelihood", "Likelihood 1-5", "number"],
                    ["controls", "Controls (hierarchy: eliminate → PPE)", "textarea"],
                    ["ppe", "PPE required", "text"],
                    ["residual", "Residual risk acceptable", "select:yes,no — additional controls required"],
                    ["review", "Next review / after change", "date"],
                    ["status", "Status", "select:current,review due,superseded"]]},
        # L3. Emergency Preparedness & Response — 14001 §8.2 · 45001 §8.2 · R2 Core 3
        {"grp": "L · SAFETY (ISO 45001)", "icon": "🚨", "key": "emergency_drills", "name": "Emergency Preparedness & Drill Log (FRM-SAF-009)", "iso": "14001 §8.2·45001 §8.2·R2 Core 3",
         "fields": [["at", "Date", "date"],
                    ["type", "Scenario", "select:fire evacuation,battery / FM fire,chemical spill (FRM-ENV-005),medical emergency,earthquake,power failure,active threat"],
                    ["kind", "Kind", "select:drill,tabletop exercise,actual event"],
                    ["participants", "Participants (count / areas)", "text"],
                    ["evac_time", "Evacuation / response time", "text"],
                    ["findings", "Findings / weaknesses", "textarea"],
                    ["actions", "Improvement actions (CAPA ref)", "textarea"],
                    ["plan_updated", "Emergency plan updated", "select:no change needed,updated,pending"],
                    ["status", "Status", "select:completed,actions open,closed"]]},
        # L4. PPE Issue & Inspection — 45001 §8.1
        {"grp": "L · SAFETY (ISO 45001)", "icon": "🧤", "key": "ppe_register", "name": "PPE Issue & Inspection (FRM-SAF-003)", "iso": "45001 §8.1",
         "fields": [["worker", "Worker", "text"], ["at", "Issue / inspection date", "date"],
                    ["ppe", "PPE items", "checks:safety glasses,gloves — cut resistant,gloves — chemical,steel-toe shoes,hi-vis vest,hearing protection,respirator / dust mask,face shield,ESD strap"],
                    ["condition", "Condition", "select:good,replaced,defective — removed from service"],
                    ["training", "Worker trained in correct use", "select:yes,scheduled"],
                    ["next", "Next inspection due", "date"]]},
        # L5. Contractor & Visitor EHS Control — 45001 §8.1.4
        {"grp": "L · SAFETY (ISO 45001)", "icon": "👷", "key": "contractors", "name": "Contractor & Visitor EHS Control (FRM-SAF-010)", "iso": "45001 §8.1.4",
         "fields": [["name", "Contractor / visitor", "text"], ["company", "Company", "text"],
                    ["at", "Date on site", "date"], ["host", "Host / escort", "text"],
                    ["purpose", "Purpose of visit / work", "text"],
                    ["induction", "EHS induction given (hazards, exits, PPE, FM areas)", "select:yes,refused — entry denied"],
                    ["insurance", "Contractor insurance / license verified", "select:yes,n/a — visitor,pending — hold"],
                    ["permit", "Work permit required (hot work, electrical, height)", "select:none,issued,denied"],
                    ["status", "Status", "select:on site,departed,work completed,closed"]]},
        # L6. Worker Consultation & Participation — 45001 §5.4
        {"grp": "L · SAFETY (ISO 45001)", "icon": "🗣️", "key": "safety_committee", "name": "Worker Consultation & Safety Committee (FRM-SAF-008)", "iso": "45001 §5.4",
         "fields": [["at", "Meeting date", "date"], ["chair", "Chair", "text"],
                    ["attendees", "Attendees (incl. worker representatives)", "textarea"],
                    ["topics", "Topics / worker concerns raised", "textarea"],
                    ["decisions", "Decisions & consultation outcomes", "textarea"],
                    ["actions", "Actions (owner / due)", "textarea"],
                    ["next", "Next meeting", "date"],
                    ["status", "Status", "select:minutes issued,actions open,closed"]]},
        # L8. Occupational Health Surveillance — 45001 §9.1.1
        {"grp": "L · SAFETY (ISO 45001)", "icon": "🩺", "key": "health_surv", "name": "Occupational Health Surveillance (FRM-SAF-011)", "iso": "45001 §9.1.1·§7.4",
         "fields": [["at", "Date", "date"],
                    ["kind", "Monitoring kind", "select:noise dosimetry,airborne dust,lead / cadmium exposure,ergonomic assessment,lighting,medical surveillance / exam,other"],
                    ["area", "Area / task", "text"], ["workers", "Workers covered", "text"],
                    ["result", "Measured result", "text"], ["limit", "OEL / action limit", "text"],
                    ["within", "Within limit", "select:yes,exceeded — CAPA raised,borderline — re-monitor"],
                    ["notified", "Workers notified of results (§7.4)", "select:yes,pending"],
                    ["by", "Performed by (hygienist / provider)", "text"],
                    ["next", "Next monitoring due", "date"],
                    ["status", "Status", "select:completed,exceedance — action open,scheduled,closed"]]},
        # N. Management System — FRM-IMS-001…007 (auditor-facing core)
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🏛️", "key": "mgmt_review", "name": "Management Review (FRM-IMS-001)", "iso": "9001·14001·45001 §9.3·R2 Core 1",
         "fields": [["at", "Review date", "date"], ["chair", "Chaired by (top management)", "text"],
                    ["attendees", "Attendees", "textarea"],
                    ["inputs", "Inputs reviewed", "checks:audit results,CAPA status,objectives & KPI performance,customer feedback,incident & near-miss trends,compliance evaluation,downstream due diligence,resource needs,risks & opportunities,previous review actions"],
                    ["decisions", "Decisions & outputs (improvements, resources, changes)", "textarea"],
                    ["actions", "Actions assigned (owner / due)", "textarea"],
                    ["next", "Next review due", "date"],
                    ["status", "Status", "select:minutes issued,actions open,closed"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🎯", "key": "objectives", "name": "Quality / EHS Objectives & KPI (FRM-IMS-002)", "iso": "9001·14001·45001 §6.2",
         "fields": [["objective", "Objective", "textarea"],
                    ["kind", "System", "select:quality (9001),environmental (14001),safety (45001),R2 / data security"],
                    ["kpi", "KPI / measure", "text"], ["target", "Target", "text"],
                    ["current", "Current performance", "text"],
                    ["owner", "Owner", "text"], ["due", "Target date", "date"],
                    ["resources", "Resources / plan", "textarea"],
                    ["status", "Status", "select:on track,at risk,achieved,missed — CAPA raised"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🔧", "key": "calibration_r2", "name": "Calibration & Equipment Maintenance (FRM-IMS-003)", "iso": "9001 §7.1.5",
         "fields": [["equipment", "Equipment (floor scale, pallet scale, test rigs, forklift)", "text"],
                    ["equip_id", "Asset / serial No.", "text"],
                    ["kind", "Kind", "select:calibration — weighing (R2 mass balance),calibration — test equipment,preventive maintenance,repair"],
                    ["at", "Done", "date"], ["by", "By (internal / vendor)", "text"],
                    ["result", "Result / certificate No.", "text"],
                    ["tolerance", "Within tolerance", "select:yes,no — quarantined & re-measured"],
                    ["next", "Next due", "date"],
                    ["status", "Status", "select:current,due,overdue,out of service"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "⚖️", "key": "material_balance", "name": "R2 Material Balance & Throughput (FRM-IMS-004)", "iso": "R2 Core 5",
         "fields": [["period", "Period (month / quarter)", "text"],
                    ["at", "Prepared", "date"], ["by", "Prepared by", "text"],
                    ["inbound_kg", "Total inbound (kg)", "number"],
                    ["resold_kg", "Reuse / resold (kg)", "number"],
                    ["recycled_kg", "To downstream recycling (kg)", "number"],
                    ["fm_kg", "Focus materials shipped (kg)", "number"],
                    ["disposal_kg", "Disposal / landfill (kg)", "number"],
                    ["onsite_kg", "Balance on site (kg)", "number"],
                    ["variance", "Variance explanation (if streams do not reconcile)", "textarea"],
                    ["status", "Status", "select:draft,reconciled,reviewed at management review"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🛡️", "key": "insurance", "name": "Insurance & Closure Plan (FRM-IMS-005)", "iso": "R2 Core 4",
         "fields": [["item", "Item", "select:pollution liability insurance,general liability,workers compensation,closure plan & cost estimate,financial assurance instrument"],
                    ["provider", "Provider / instrument", "text"],
                    ["coverage", "Coverage / amount", "text"],
                    ["expiry", "Expiry / review date", "date"],
                    ["verified_by", "Verified by", "text"],
                    ["status", "Status", "select:current,renewal due,lapsed — escalate"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "📣", "key": "complaints_fb", "name": "Customer Complaint & Feedback (FRM-IMS-006)", "iso": "9001 §9.1.2·10.2",
         "fields": [["at", "Received", "date"], ["customer", "Customer", "text"],
                    ["channel", "Channel", "select:email,phone,marketplace review,on-site,other"],
                    ["subject", "Subject / order ref", "text"],
                    ["desc", "Complaint / feedback", "textarea"],
                    ["classification", "Classification", "select:product quality,data security concern,delivery,service,positive feedback"],
                    ["action", "Containment & resolution", "textarea"],
                    ["capa", "CAPA raised (FRM-QC-004)", "select:no,yes — ref in action"],
                    ["status", "Status", "select:open,investigating,resolved,closed"]]},
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🤝", "key": "supplier_eval", "name": "Upstream Supplier Evaluation (FRM-IMS-007)", "iso": "9001 §8.4·R2 Core 5",
         "fields": [["supplier", "Supplier / source", "text"],
                    ["kind", "Kind", "select:equipment supplier,ITAD client,broker,municipal / collection,parts vendor,service provider"],
                    ["criteria", "Evaluation criteria (quality, legality of supply, data handling, delivery)", "textarea"],
                    ["score", "Score / rating", "text"],
                    ["at", "Evaluated", "date"], ["by", "Evaluated by", "text"],
                    ["next", "Re-evaluation due", "date"],
                    ["status", "Status", "select:approved,conditional,suspended,removed"]]},
        # N8. Management of Change — 45001 §8.1.3 · 9001 §6.3 · 14001 §8.1
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🔄", "key": "moc", "name": "Management of Change (FRM-IMS-008)", "iso": "9001 §6.3·14001 §8.1·45001 §8.1.3",
         "fields": [["at", "Proposed", "date"], ["by", "Proposed by", "text"],
                    ["change", "Change description (process, equipment, layout, chemical, staffing, downstream)", "textarea"],
                    ["reason", "Reason / driver", "text"],
                    ["impacts", "Impact review", "checks:quality / product conformity,environmental aspects (FRM-ENV-001),safety hazards — JHA update (FRM-SAF-002),data security (Core 7),permits / legal (FRM-ENV-004),training needs,documents to update"],
                    ["approval", "Approved by (management)", "text"],
                    ["implemented", "Implemented", "date"],
                    ["verified", "Post-change verification (controls effective)", "select:pending,verified,issues — CAPA raised"],
                    ["status", "Status", "select:proposed,approved,in progress,implemented,verified,rejected"]]},
        # N9. Communication Register — 14001 §7.4 · 45001 §7.4 · 9001 §7.4
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "📢", "key": "communications", "name": "Internal & External Communication Log (FRM-IMS-009)", "iso": "9001·14001·45001 §7.4",
         "fields": [["at", "Date", "date"], ["direction", "Direction", "select:internal — all staff,internal — department,external — customer,external — regulator / agency,external — community / neighbor,external — downstream vendor"],
                    ["topic", "Topic", "select:policy / objectives,EHS alert / hazard,regulatory correspondence,environmental inquiry / complaint,audit notification,procedure change,emergency information,other"],
                    ["summary", "Summary", "textarea"],
                    ["by", "Communicated by", "text"],
                    ["response", "Response / follow-up required", "select:none,yes — action logged"],
                    ["status", "Status", "select:sent / posted,response pending,closed"]]},
        # N10. Competency & Authorization Matrix — §7.2 all standards · R2 Core 7:
        #      only named, authorized persons may sanitize data / handle FM.
        {"grp": "N · MANAGEMENT SYSTEM (IMS)", "icon": "🎓", "key": "competency", "name": "Competency & Authorization Matrix (FRM-IMS-010)", "iso": "9001·14001·45001 §7.2·R2 Core 7",
         "fields": [["person", "Person", "text"],
                    ["role", "Authorized role", "select:data sanitization operator,sanitization verifier (independent),focus material handler,forklift / MHE operator,final QC inspector,dismantling technician,secure area access,first aider,other"],
                    ["training", "Training completed (method / SOP refs)", "textarea"],
                    ["evaluated", "Competency evaluated by", "text"],
                    ["eval_at", "Evaluation date", "date"],
                    ["probation", "Supervised probation completed", "select:yes,in progress,n/a"],
                    ["expires", "Authorization expires", "date"],
                    ["status", "Status", "select:authorized,probation,expired — renewal due,revoked"]]},
    ]},
    "importer": {"label": "Importer", "icon": "🚢", "modules": [
        {"key": "shipments", "name": "Shipment Register", "iso": "9001 §8.5",
         "fields": [["po", "PO #", "text"], ["supplier", "Supplier", "text"],
                    ["origin", "Origin", "text"], ["eta", "ETA", "date"],
                    ["status", "Status", "select:ordered,in production,shipped,customs,delivered"],
                    ["container", "Container #", "text"]]},
        {"key": "customs", "name": "Customs Entry & Duty Log", "iso": "9001 §8.4",
         "fields": [["entry", "Entry #", "text"], ["hts", "HTS code", "text"],
                    ["duty", "Duty $", "number"], ["broker", "Broker", "text"], ["cleared", "Cleared date", "date"]]},
        {"key": "supplier_audit", "name": "Supplier Audit Register", "iso": "9001 §8.4.2",
         "fields": [["supplier", "Supplier", "text"], ["at", "Audit date", "date"],
                    ["score", "Score %", "number"], ["findings", "Findings", "textarea"], ["next", "Next audit", "date"]]},
        {"key": "qc", "name": "Incoming QC Inspection", "iso": "9001 §8.6",
         "fields": [["po", "PO #", "text"], ["sku", "SKU", "text"], ["sampled", "Sampled qty", "number"],
                    ["defects", "Defects", "number"], ["result", "Result", "select:pass,conditional,reject"]]},
    ]},
    "freight": {"label": "Freight Forwarder", "icon": "✈️", "modules": [
        {"key": "bookings", "name": "Booking Register", "iso": "9001 §8.2",
         "fields": [["ref", "Booking ref", "text"], ["client", "Client", "text"],
                    ["mode", "Mode", "select:ocean FCL,ocean LCL,air,truck,rail"],
                    ["pol", "Origin", "text"], ["pod", "Destination", "text"],
                    ["etd", "ETD", "date"], ["status", "Status", "select:booked,in transit,arrived,delivered,invoiced"]]},
        {"key": "bl", "name": "B/L & AWB Document Log", "iso": "9001 §7.5",
         "fields": [["ref", "Shipment ref", "text"], ["doc", "Document", "select:MBL,HBL,MAWB,HAWB,invoice,packing list,CO"],
                    ["number", "Doc #", "text"], ["issued", "Issued", "date"], ["status", "Status", "select:draft,issued,surrendered,released"]]},
        {"key": "carriers", "name": "Carrier Rate & Performance", "iso": "9001 §8.4",
         "fields": [["carrier", "Carrier", "text"], ["lane", "Lane", "text"],
                    ["rate", "Rate $", "number"], ["transit", "Transit days", "number"], ["otp", "On-time %", "number"]]},
        {"key": "claims", "name": "Cargo Claim Register", "iso": "9001 §10.2",
         "fields": [["ref", "Shipment ref", "text"], ["at", "Date", "date"],
                    ["type", "Type", "select:damage,shortage,delay,loss"], ["amount", "Amount $", "number"],
                    ["status", "Status", "select:filed,negotiating,settled,rejected"]]},
    ]},
    "trucking": {"label": "Trucking", "icon": "🚛", "modules": [
        {"key": "dispatch", "name": "Dispatch Board", "iso": "9001 §8.5",
         "fields": [["load", "Load #", "text"], ["driver", "Driver", "text"],
                    ["pickup", "Pickup", "text"], ["drop", "Delivery", "text"],
                    ["date", "Date", "date"], ["rate", "Rate $", "number"],
                    ["status", "Status", "select:planned,dispatched,in transit,delivered,invoiced"]]},
        {"key": "fleet", "name": "Fleet Maintenance Register", "iso": "9001 §7.1.3",
         "fields": [["unit", "Unit #", "text"], ["service", "Service", "text"],
                    ["odo", "Odometer", "number"], ["at", "Date", "date"], ["next", "Next due", "date"]]},
        {"key": "hos", "name": "Driver Hours / DOT Compliance", "iso": "45001 §8.1",
         "fields": [["driver", "Driver", "text"], ["at", "Date", "date"],
                    ["hours", "Driving hours", "number"], ["violation", "Violation", "select:none,HOS,logbook,speeding"],
                    ["note", "Note", "textarea"]]},
        {"key": "dvir", "name": "Vehicle Inspection (DVIR) Log", "iso": "45001 §8.1.2",
         "fields": [["unit", "Unit #", "text"], ["driver", "Driver", "text"], ["at", "Date", "date"],
                    ["defects", "Defects found", "textarea"], ["safe", "Safe to operate", "select:yes,no"]]},
    ]},
    "technology": {"label": "Technology Company", "icon": "💻", "modules": [
        {"key": "releases", "name": "Release & Change Register", "iso": "25010·9001 §8.5.6",
         "fields": [["version", "Version", "text"], ["at", "Release date", "date"],
                    ["scope", "Scope", "textarea"], ["risk", "Risk", "select:low,medium,high"],
                    ["status", "Status", "select:planned,in QA,released,rolled back"]]},
        {"key": "incidents", "name": "Incident & Problem Log", "iso": "25010·9001 §10.2",
         "fields": [["at", "Date", "date"], ["sev", "Severity", "select:SEV1,SEV2,SEV3,SEV4"],
                    ["service", "Service", "text"], ["desc", "Description", "textarea"],
                    ["rca", "Root cause", "textarea"], ["status", "Status", "select:open,mitigated,resolved,postmortem done"]]},
        {"key": "quality", "name": "Software Quality Metrics (ISO 25010)", "iso": "25010 §4",
         "fields": [["at", "Date", "date"], ["metric", "Characteristic", "select:functional suitability,reliability,performance efficiency,usability,security,maintainability,portability,compatibility"],
                    ["value", "Measured value", "text"], ["target", "Target", "text"], ["pass", "Meets target", "select:yes,no"]]},
        {"key": "assets", "name": "IT Asset & License Register", "iso": "9001 §7.1.3",
         "fields": [["asset", "Asset", "text"], ["type", "Type", "select:hardware,software license,cloud subscription,certificate"],
                    ["owner", "Owner", "text"], ["expiry", "Renewal/expiry", "date"], ["cost", "Annual cost $", "number"]]},
    ]},
    "auto_repair": {"label": "Auto Repair Shop", "icon": "🔧", "modules": [
        {"key": "workorders", "name": "Work Order Board", "iso": "9001 §8.5",
         "fields": [["ro", "RO #", "text"], ["vehicle", "Vehicle", "text"], ["customer", "Customer", "text"],
                    ["complaint", "Complaint", "textarea"], ["tech", "Technician", "text"],
                    ["status", "Status", "select:estimate,approved,in progress,waiting parts,QC,delivered"]]},
        {"key": "parts", "name": "Parts Order Register", "iso": "9001 §8.4",
         "fields": [["ro", "RO #", "text"], ["part", "Part", "text"], ["vendor", "Vendor", "text"],
                    ["cost", "Cost $", "number"], ["eta", "ETA", "date"], ["status", "Status", "select:ordered,backorder,received,installed,returned"]]},
        {"key": "qc_final", "name": "Final QC / Road Test Checklist", "iso": "9001 §8.6",
         "fields": [["ro", "RO #", "text"], ["tech", "Inspector", "text"], ["at", "Date", "date"],
                    ["items", "Checks performed", "textarea"], ["result", "Result", "select:pass,rework"]]},
        {"key": "hazmat", "name": "Hazardous Material / Fluid Disposal", "iso": "14001 §8.1",
         "fields": [["at", "Date", "date"], ["material", "Material", "select:used oil,coolant,batteries,tires,solvents,refrigerant"],
                    ["qty", "Quantity", "number"], ["carrier", "Disposal service", "text"]]},
    ]},
    "ecommerce": {"label": "E-Commerce", "icon": "🛒", "modules": [
        {"key": "orders", "name": "Order Exception Register", "iso": "9001 §8.7",
         "fields": [["order", "Order #", "text"], ["at", "Date", "date"],
                    ["issue", "Issue", "select:delayed,lost,damaged,wrong item,payment,fraud"],
                    ["resolution", "Resolution", "textarea"], ["status", "Status", "select:open,resolved,refunded,replaced"]]},
        {"key": "returns", "name": "Returns / RMA Log", "iso": "9001 §8.7·10.2",
         "fields": [["rma", "RMA #", "text"], ["order", "Order #", "text"], ["sku", "SKU", "text"],
                    ["reason", "Reason", "text"], ["status", "Status", "select:requested,approved,received,refunded,rejected"]]},
        {"key": "inventory", "name": "Inventory Reorder Register", "iso": "9001 §8.5.4",
         "fields": [["sku", "SKU", "text"], ["stock", "On hand", "number"], ["reorder", "Reorder point", "number"],
                    ["supplier", "Supplier", "text"], ["leadtime", "Lead time (days)", "number"]]},
        {"key": "reviews", "name": "Customer Feedback & NPS Log", "iso": "9001 §9.1.2",
         "fields": [["at", "Date", "date"], ["channel", "Channel", "select:review,email,chat,social"],
                    ["score", "Score (1-10)", "number"], ["comment", "Comment", "textarea"], ["action", "Action taken", "textarea"]]},
    ]},
    "auto_dealer": {"label": "Auto Dealer", "icon": "🚗", "modules": [
        {"key": "stock", "name": "Vehicle Inventory Register", "iso": "9001 §8.5.4",
         "fields": [["stock_no", "Stock #", "text"], ["vin", "VIN", "text"], ["vehicle", "Year/Make/Model", "text"],
                    ["cost", "Cost $", "number"], ["price", "Asking $", "number"], ["days", "Days in stock", "number"],
                    ["status", "Status", "select:in recon,front line,pending,sold,wholesale"]]},
        {"key": "deals", "name": "Deal Jacket Checklist", "iso": "9001 §7.5·8.5",
         "fields": [["deal", "Deal #", "text"], ["customer", "Customer", "text"], ["vehicle", "Vehicle", "text"],
                    ["docs", "Docs complete", "select:no,partial,yes"], ["funding", "Funding status", "select:cash,pending,funded"],
                    ["delivered", "Delivered", "date"]]},
        {"key": "recon", "name": "Reconditioning Work Log", "iso": "9001 §8.5.1",
         "fields": [["stock_no", "Stock #", "text"], ["task", "Task", "text"], ["vendor", "Vendor/Tech", "text"],
                    ["cost", "Cost $", "number"], ["status", "Status", "select:pending,in progress,done"]]},
        {"key": "compliance", "name": "Title / DMV Compliance Register", "iso": "9001 §8.5.3",
         "fields": [["deal", "Deal #", "text"], ["item", "Item", "select:title,registration,plates,smog,safety recall"],
                    ["due", "Due", "date"], ["status", "Status", "select:pending,submitted,complete"]]},
    ]},
    "clinic": {"label": "Clinic", "icon": "🏥", "modules": [
        {"key": "appts", "name": "Appointment & No-Show Register", "iso": "9001 §8.2",
         "fields": [["at", "Date", "date"], ["patient", "Patient ref", "text"], ["provider", "Provider", "text"],
                    ["type", "Visit type", "text"], ["status", "Status", "select:scheduled,arrived,completed,no-show,cancelled"]]},
        {"key": "sterilization", "name": "Sterilization / Autoclave Log", "iso": "9001·45001 §8.1",
         "fields": [["at", "Date", "date"], ["cycle", "Cycle #", "text"], ["temp", "Temp °C", "number"],
                    ["indicator", "Biological indicator", "select:pass,fail"], ["by", "Operated by", "text"]]},
        {"key": "meds", "name": "Medication / Vaccine Fridge Log", "iso": "9001 §7.1.5",
         "fields": [["at", "Date", "date"], ["unit", "Fridge", "text"], ["temp", "Temp °C", "number"],
                    ["in_range", "In range 2-8°C", "select:yes,no"], ["action", "Action if out", "textarea"]]},
        {"key": "incidents", "name": "Patient Safety Incident Register", "iso": "45001 §10.2",
         "fields": [["at", "Date", "date"], ["type", "Type", "select:medication error,fall,needle-stick,equipment,other"],
                    ["desc", "Description", "textarea"], ["capa", "Corrective action", "textarea"],
                    ["reported", "Reported to authority", "select:n/a,yes,no"]]},
    ]},
    "doctor": {"label": "Medical Doctor", "icon": "🩺", "modules": [
        {"key": "referrals", "name": "Referral Tracking Register", "iso": "9001 §8.2",
         "fields": [["at", "Date", "date"], ["patient", "Patient ref", "text"], ["to", "Referred to", "text"],
                    ["reason", "Reason", "text"], ["status", "Status", "select:sent,scheduled,seen,report received"]]},
        {"key": "results", "name": "Lab / Imaging Result Follow-up", "iso": "9001 §8.6",
         "fields": [["at", "Ordered", "date"], ["patient", "Patient ref", "text"], ["test", "Test", "text"],
                    ["received", "Result received", "date"], ["reviewed", "Reviewed & actioned", "select:pending,yes"]]},
        {"key": "cme", "name": "CME / License Register", "iso": "9001 §7.2",
         "fields": [["item", "Credential", "text"], ["hours", "CME hours", "number"],
                    ["expiry", "Expiry", "date"], ["status", "Status", "select:valid,renewal due,expired"]]},
        {"key": "complaints", "name": "Patient Complaint & Feedback", "iso": "9001 §9.1.2·10.2",
         "fields": [["at", "Date", "date"], ["summary", "Summary", "textarea"],
                    ["severity", "Severity", "select:low,medium,high"], ["resolution", "Resolution", "textarea"]]},
    ]},
    "laboratory": {"label": "Laboratory", "icon": "🔬", "modules": [
        {"key": "samples", "name": "Sample Chain-of-Custody Log", "iso": "17025·9001 §8.5.4",
         "fields": [["sample", "Sample ID", "text"], ["received", "Received", "date"], ["from", "Client/Source", "text"],
                    ["test", "Requested tests", "text"], ["status", "Status", "select:received,testing,reported,archived,disposed"]]},
        {"key": "calibration", "name": "Equipment Calibration Register", "iso": "17025 §6.4·9001 §7.1.5",
         "fields": [["equip", "Equipment", "text"], ["serial", "Serial #", "text"],
                    ["last", "Last calibrated", "date"], ["next", "Next due", "date"],
                    ["status", "Status", "select:in tolerance,due,out of service"]]},
        {"key": "qc_runs", "name": "QC Run / Control Chart Log", "iso": "17025 §7.7",
         "fields": [["at", "Date", "date"], ["assay", "Assay", "text"], ["control", "Control lot", "text"],
                    ["value", "Value", "number"], ["in_range", "Within limits", "select:yes,no"], ["action", "Action if out", "textarea"]]},
        {"key": "reagents", "name": "Reagent Lot & Expiry Register", "iso": "9001 §8.5.2",
         "fields": [["reagent", "Reagent", "text"], ["lot", "Lot #", "text"],
                    ["opened", "Opened", "date"], ["expiry", "Expiry", "date"],
                    ["status", "Status", "select:in use,quarantine,expired,disposed"]]},
    ]},
    "supermarket": {"label": "Supermarket", "icon": "🛍️", "modules": [
        {"key": "coldchain", "name": "Cold Chain Temperature Log", "iso": "9001·22000",
         "fields": [["at", "Date", "date"], ["unit", "Case/Freezer", "text"], ["temp", "Temp °C", "number"],
                    ["in_range", "In range", "select:yes,no"], ["action", "Corrective action", "textarea"]]},
        {"key": "expiry", "name": "Expiry Date Rotation Register", "iso": "9001 §8.5.4",
         "fields": [["sku", "Product", "text"], ["lot", "Lot", "text"], ["expiry", "Expiry", "date"],
                    ["qty", "Qty", "number"], ["action", "Action", "select:rotate,markdown,remove,donate"]]},
        {"key": "recalls", "name": "Product Recall Register", "iso": "9001 §8.7·10.2",
         "fields": [["at", "Date", "date"], ["product", "Product", "text"], ["lot", "Affected lots", "text"],
                    ["qty", "Qty pulled", "number"], ["status", "Status", "select:notified,pulled,returned,closed"]]},
        {"key": "shrink", "name": "Shrink / Loss Prevention Log", "iso": "9001 §9.1",
         "fields": [["at", "Date", "date"], ["dept", "Department", "text"],
                    ["type", "Type", "select:damage,theft,expiry,admin error"], ["value", "Value $", "number"],
                    ["note", "Note", "textarea"]]},
    ]},
}

# ============================================================
# ERP CORE — universal enterprise modules every commercial
# deployment gets: Sales, Supply chain, HR, Finance.
# Together with the industry OPERATIONS modules and the ISO
# COMPLIANCE core they form a complete AI-powered ERP.
# ============================================================
ERP_MODULES: list[dict] = [
    # ---------- SALES ----------
    {"key": "pos_sales", "name": "POS / Sales Register", "iso": "9001 §8.2", "cat": "SALES", "icon": "🧾",
     "fields": [["at", "Date", "date"], ["receipt", "Receipt / Order #", "text"],
                ["items", "Items sold", "textarea"], ["qty", "Qty", "number"],
                ["total", "Total $", "number"],
                ["payment", "Payment", "select:cash,card,online,transfer,on account"],
                ["staff", "Staff", "text"]]},
    {"key": "customers", "name": "Customer Directory (CRM)", "iso": "9001 §8.2.1", "cat": "SALES", "icon": "🤝",
     "fields": [["name", "Customer", "text"], ["contact", "Contact person", "text"],
                ["phone", "Phone", "text"], ["email", "Email", "text"],
                ["type", "Type", "select:retail,wholesale,corporate,VIP"],
                ["notes", "Notes", "textarea"]]},
    {"key": "invoices", "name": "Invoicing (A/R)", "iso": "9001 §8.2·7.5", "cat": "SALES", "icon": "📄",
     "fields": [["invoice", "Invoice #", "text"], ["customer", "Customer", "text"],
                ["at", "Invoice date", "date"], ["due", "Due date", "date"],
                ["amount", "Amount $", "number"], ["tax", "Tax $", "number"],
                ["status", "Status", "select:draft,sent,partially paid,paid,overdue,void"]]},
    {"key": "quotes", "name": "Quotations / Estimates", "iso": "9001 §8.2.3", "cat": "SALES", "icon": "🧮",
     "fields": [["quote", "Quote #", "text"], ["customer", "Customer", "text"],
                ["at", "Date", "date"], ["scope", "Scope / items", "textarea"],
                ["amount", "Amount $", "number"], ["valid", "Valid until", "date"],
                ["status", "Status", "select:draft,sent,accepted,declined,expired"]]},
    # ---------- SUPPLY CHAIN ----------
    {"key": "inventory", "name": "Inventory Management", "iso": "9001 §8.5.4", "cat": "SUPPLY", "icon": "📦",
     "fields": [["sku", "SKU / Code", "text"], ["name", "Item", "text"],
                ["category", "Category", "text"], ["qty", "On hand", "number"],
                ["unit", "Unit", "text"], ["reorder", "Reorder point", "number"],
                ["cost", "Unit cost $", "number"], ["price", "Sell price $", "number"],
                ["location", "Location / Bin", "text"]]},
    {"key": "purchase_orders", "name": "Purchase Orders (A/P)", "iso": "9001 §8.4", "cat": "SUPPLY", "icon": "🛒",
     "fields": [["po", "PO #", "text"], ["supplier", "Supplier", "text"],
                ["at", "Order date", "date"], ["items", "Items", "textarea"],
                ["amount", "Amount $", "number"], ["eta", "Expected", "date"],
                ["status", "Status", "select:draft,sent,confirmed,partially received,received,paid,cancelled"]]},
    # ---------- HR ----------
    {"key": "workers", "name": "Employee Enrollment (HR)", "iso": "9001·45001 §7.2", "cat": "HR", "icon": "👷",
     "fields": [["_s1", "🪪 Employee Identity", "section"],
                ["name", "Legal full name", "text"], ["dob", "Date of birth", "date"],
                ["gender", "Gender", "select:—,female,male,non-binary,prefer not to say"],
                ["ssn", "SSN / Tax ID (kept private)", "text"],
                ["_s2", "💼 Employment", "section"],
                ["role", "Role / Position", "text"],
                ["management", "Management position", "select:no,yes"],
                ["hired", "Hire date", "date"], ["wage", "Wage / Salary $", "number"],
                ["status", "Status", "select:active,on leave,terminated"],
                ["_s3", "🔐 Platform Access Credentials", "section"],
                ["login_username", "Login username (platform account)", "text"],
                ["login_password", "Login password (min 8 chars)", "password"],
                ["_s4", "📞 Contact Details", "section"],
                ["phone", "Phone", "text"], ["email", "Email", "text"],
                ["address", "Address", "text"],
                ["emergency", "Emergency contact", "text"]]},
    {"key": "timesheets", "name": "Timesheets & Attendance", "iso": "45001 §7.2", "cat": "HR", "icon": "⏱️",
     "fields": [["worker", "Worker", "text"], ["at", "Date", "date"],
                ["hours", "Hours", "number"], ["ot", "Overtime", "number"],
                ["shift", "Shift", "select:morning,afternoon,evening,night,split"],
                ["note", "Note", "textarea"]]},
    {"key": "hr_injury", "name": "Employee Injury Register", "iso": "45001 §10.2 · OSHA 300", "cat": "HR", "icon": "🩹",
     "fields": [["worker", "Employee", "text"], ["at", "Incident date", "date"],
                ["type", "Classification", "select:near miss,first aid,medical treatment,restricted duty,lost time,fatality"],
                ["body_part", "Body part / injury", "text"],
                ["desc", "Description of incident", "textarea"],
                ["days_lost", "Days away / restricted", "number"],
                ["reported", "Reported to authority", "select:n/a,yes,no"],
                ["capa", "Corrective / preventive action", "textarea"],
                ["status", "Status", "select:open,investigating,action taken,closed"]]},
    {"key": "hr_violation", "name": "Employee Violation / Disciplinary Log", "iso": "9001 §7.3·45001 §5.4", "cat": "HR", "icon": "⚖️",
     "fields": [["worker", "Employee", "text"], ["at", "Date", "date"],
                ["type", "Category", "select:safety,policy,attendance,conduct,harassment,quality,other"],
                ["desc", "Description", "textarea"],
                ["action", "Disciplinary action", "select:coaching,verbal warning,written warning,final warning,suspension,termination"],
                ["issued_by", "Issued by", "text"],
                ["ack", "Employee acknowledged", "select:pending,yes,refused"],
                ["status", "Status", "select:open,under review,closed"]]},
    {"key": "hr_separation", "name": "Employee Quit / Separation Register", "iso": "9001 §7.2·7.5", "cat": "HR", "icon": "🚪",
     "fields": [["worker", "Employee", "text"], ["at", "Last working day", "date"],
                ["type", "Separation type", "select:resignation with notice,quit without notice,termination,layoff,retirement,end of contract"],
                ["reason", "Reason / notes", "textarea"],
                ["assets", "Company assets returned", "select:pending,yes,partial,n/a"],
                ["final_pay", "Final pay settled", "select:pending,yes"],
                ["exit_interview", "Exit interview summary", "textarea"],
                ["rehire", "Eligible for rehire", "select:yes,no,case by case"]]},
    # ---------- FINANCE (CPA-style, GAAP double-entry) ----------
    {"key": "coa", "name": "Chart of Accounts (GAAP)", "iso": "9001 §7.5", "cat": "FINANCE", "icon": "🧾",
     "fields": [["acct_no", "Account #", "text"], ["account", "Account name", "text"],
                ["type", "Type", "select:Asset,Contra-Asset,Liability,Equity,Revenue,COGS,Operating Expense,Other Income,Other Expense"],
                ["normal", "Normal balance", "select:debit,credit"],
                ["active", "Active", "select:yes,no"],
                ["note", "Description", "textarea"]]},
    {"key": "ledger", "name": "General Ledger (Double-Entry)", "iso": "9001 §7.5", "cat": "FINANCE", "icon": "📚",
     "fields": [["at", "Date", "date"], ["je", "Journal entry #", "text"],
                ["account", "Account", "text"],
                ["type", "Type", "select:income,expense,asset,liability,equity"],
                ["debit", "Debit $", "number"], ["credit", "Credit $", "number"],
                ["memo", "Memo / supporting document ref", "textarea"]]},
    {"key": "expenses", "name": "Expense Tracking", "iso": "9001 §7.5", "cat": "FINANCE", "icon": "💸",
     "fields": [["at", "Date", "date"],
                ["category", "Category", "select:rent,utilities,payroll,supplies,marketing,insurance,maintenance,fuel,other"],
                ["vendor", "Vendor", "text"], ["amount", "Amount $", "number"],
                ["payment", "Payment", "select:cash,card,transfer,check"],
                ["note", "Note", "textarea"]]},
]

# ------------------------------------------------------------
# CPA-style industry Chart of Accounts — the General Ledger's
# ACCOUNT field becomes a curated GAAP account list per industry
# (base accounts + industry-specific accounts).
# ------------------------------------------------------------
_COA_BASE: list[str] = [
    "1000 · Cash & Cash Equivalents", "1100 · Accounts Receivable",
    "1200 · Inventory", "1500 · Fixed Assets — Equipment",
    "1510 · Accumulated Depreciation", "2000 · Accounts Payable",
    "2100 · Payroll Liabilities", "2200 · Sales Tax Payable",
    "2500 · Loans Payable", "3000 · Owner's Equity",
    "3900 · Retained Earnings", "4000 · Sales Revenue",
    "4900 · Returns & Allowances", "5000 · Cost of Goods Sold",
    "6000 · Payroll Expense", "6100 · Rent & Occupancy",
    "6200 · Utilities", "6300 · Insurance Expense",
    "6400 · Marketing & Advertising", "6500 · Office & Supplies",
    "6600 · Repairs & Maintenance", "6700 · Professional Fees",
    "6800 · Depreciation Expense", "7000 · Other Income", "8000 · Other Expense",
]
_COA_INDUSTRY: dict[str, list[str]] = {
    "retail": ["1210 · Merchandise Inventory", "4100 · POS Sales — In-store",
               "4110 · Online Sales", "5100 · Freight-In", "5200 · Inventory Shrinkage"],
    "restaurant": ["1210 · Food Inventory", "1220 · Beverage Inventory",
                   "4100 · Food Sales", "4110 · Beverage Sales", "4120 · Catering Revenue",
                   "5100 · Food Cost", "5110 · Beverage Cost", "2110 · Tips Payable",
                   "6210 · Kitchen Smallwares"],
    "warehouse": ["4100 · Storage & Handling Revenue", "4110 · Cross-Dock Revenue",
                  "5100 · Freight & Drayage", "6210 · Warehouse Equipment Lease",
                  "6220 · Racking & MHE Maintenance"],
    "fulfillment": ["4100 · Pick & Pack Revenue", "4110 · Storage Fees",
                    "4120 · Shipping Recharge Revenue", "5100 · Carrier Postage Cost",
                    "5110 · Packaging Materials", "2110 · Client Deposits Held"],
    "realtor": ["4100 · Commission Income — Sales", "4110 · Commission Income — Leasing",
                "5100 · Commission Splits / Referral Fees", "6210 · MLS & Board Dues",
                "6220 · E&O Insurance", "6230 · Staging & Photography"],
    "contractor": ["1300 · Work in Progress (WIP)", "4100 · Service / Labor Revenue",
                   "4110 · Materials Billed", "5100 · Job Materials Cost",
                   "5110 · Subcontractor Cost", "2110 · Customer Deposits",
                   "6210 · Tools & Equipment", "6220 · Vehicle & Fuel", "6230 · Bonding & Permits"],
    "insurance": ["4100 · Commission Income — New Business", "4110 · Commission Income — Renewals",
                  "4120 · Contingent / Bonus Income", "2110 · Premiums Held in Trust",
                  "6210 · E&O Insurance", "6220 · Licensing & CE Fees"],
    "recycle": ["1210 · Raw Material Inventory", "1220 · Refurbished Goods Inventory",
                "4100 · Refurbished Sales", "4110 · Scrap / Commodity Sales",
                "4120 · Data Destruction Service Revenue", "5100 · Material Acquisition Cost",
                "5110 · Data Sanitising Vendor Cost", "6210 · Environmental Compliance Fees",
                "6220 · Hazmat Disposal"],
}

# universal modules present for EVERY commercial profile (custom types too) —
# the ISO management-system core
UNIVERSAL_MODULES: list[dict] = [
    {"key": "capa", "name": "CAPA — Corrective & Preventive Actions", "iso": "9001 §10.2",
     "fields": [["at", "Raised", "date"], ["source", "Source", "select:audit,complaint,incident,inspection,management review"],
                ["nc", "Nonconformity", "textarea"], ["root_cause", "Root cause", "textarea"],
                ["action", "Action", "textarea"], ["owner", "Owner", "text"],
                ["due", "Due", "date"], ["status", "Status", "select:open,in progress,verify effectiveness,closed"]]},
    {"key": "audits", "name": "Internal Audit Programme", "iso": "9001 §9.2",
     "fields": [["area", "Area / process", "text"], ["at", "Audit date", "date"],
                ["auditor", "Auditor", "text"], ["findings", "Findings", "textarea"],
                ["ncs", "# Nonconformities", "number"], ["status", "Status", "select:planned,done,report issued,closed"]]},
    {"key": "risks", "name": "Risk & Opportunity Register", "iso": "9001 §6.1·45001 §6.1",
     "fields": [["risk", "Risk / opportunity", "textarea"], ["type", "Type", "select:quality,environment,safety,information,business"],
                ["likelihood", "Likelihood 1-5", "number"], ["impact", "Impact 1-5", "number"],
                ["mitigation", "Mitigation", "textarea"], ["owner", "Owner", "text"]]},
    {"key": "training", "name": "Competence & Training Matrix", "iso": "9001 §7.2·45001 §7.2",
     "fields": [["person", "Person", "text"], ["training", "Training / competence", "text"],
                ["at", "Completed", "date"], ["expiry", "Re-certification due", "date"],
                ["status", "Status", "select:current,due,overdue"]]},
    {"key": "docs_control", "name": "Controlled Document Register", "iso": "9001 §7.5",
     "fields": [["doc", "Document", "text"], ["version", "Version", "text"],
                ["owner", "Owner", "text"], ["approved", "Approved", "date"], ["review", "Next review", "date"]]},
]

TYPE_KEYS = list(INDUSTRY_TEMPLATES.keys())


# industry-specific extra HR fields (inserted before "emergency")
_WORKER_EXTRA_FIELDS: dict[str, list] = {
    "restaurant": [["tips_ratio", "Tips Ratio %", "number"]],
}


def modules_for(company_type: str, user_id: "str | None" = None) -> list[dict]:
    """Full ERP module set: industry OPERATIONS + universal ERP core
    (Sales / Supply / HR / Finance) + ISO COMPLIANCE core.

    OPERATIONS are externalized: when the tenant (user_id) has an
    Operations Package installed, its modules REPLACE the built-in
    industry template.  The ERP + COMPLIANCE cores are universal and
    always present regardless of package."""
    ops: list[dict] = []
    pkg = None
    if user_id:
        try:
            from . import ops_package as _opk
            pkg = _opk.load_package(user_id)
        except Exception:  # noqa: BLE001 — package layer must never break ERP
            pkg = None
    if pkg:
        ops = [dict(m, cat="OPERATIONS", icon=m.get("icon") or "🏭")
               for m in pkg["modules"]]
    else:
        t = INDUSTRY_TEMPLATES.get(company_type)
        ops = [dict(m, cat="OPERATIONS", icon=m.get("icon", "🏭"))
               for m in (t["modules"] if t else [])]
    erp = [dict(m) for m in ERP_MODULES]
    extra = _WORKER_EXTRA_FIELDS.get(company_type)
    if extra:
        for m in erp:
            if m["key"] == "workers":
                fields = [list(f) for f in m["fields"]]
                pos = next((i for i, f in enumerate(fields) if f[0] == "emergency"),
                           len(fields))
                m["fields"] = fields[:pos] + [list(f) for f in extra] + fields[pos:]
    # CPA-style industry chart of accounts — the General Ledger ACCOUNT
    # field becomes a curated GAAP select for this industry
    accounts = _COA_BASE + _COA_INDUSTRY.get(company_type, [])
    for m in erp:
        if m["key"] == "ledger":
            fields = [list(f) for f in m["fields"]]
            for f in fields:
                if f[0] == "account":
                    f[2] = "select:" + ",".join(a.replace(",", ";") for a in accounts)
            m["fields"] = fields
    comp = [dict(m, cat="COMPLIANCE", icon=m.get("icon", "🛡️")) for m in UNIVERSAL_MODULES]
    return ops + erp + comp


def template_label(company_type: str, custom_type: str = "") -> str:
    t = INDUSTRY_TEMPLATES.get(company_type)
    return t["label"] if t else (custom_type or "Custom Business")


# ============================================================
# CROSS-FORM CASCADES — when a record in one register contains
# data that belongs to a RELATED register (e.g. Receiving flags
# data-bearing media → Data Security log), the related record is
# created automatically so workers never re-key the same data.
# Rules are value-driven: they fire only when the trigger field
# matches, and only for registers present in the workspace.
# ============================================================
# rule: {"when": (field, match), "target": module_key,
#        "map": {src_field: dst_field}, "set": {dst_field: fixed},
#        "reason": human explanation for the audit trail}
# match: "yes*"-style prefix, "!" + value = not-equal, "*sub*" = contains
def _match(value: str, pat: str) -> bool:
    v = (value or "").strip().lower()
    p = pat.lower()
    if p.startswith("!"):
        return v != "" and v != p[1:]
    if p.startswith("*") and p.endswith("*"):
        return p.strip("*") in v
    if p.endswith("*"):
        return v.startswith(p[:-1])
    return v == p


_FM_MAP = {"batteries": "batteries", "crt": "CRT glass", "lcd-hg": "mercury / LCD-Hg",
           "pcb": "PCB", "solar": "solar panels / PV", "multiple": "other"}

CASCADE_RULES: dict[str, list[dict]] = {
    # A · Receiving (FRM-REC-001)
    "inbound": [
        {"when": ("data_bearing", "yes*"), "target": "media_security",
         "map": {"lot": "source", "at": "at"},
         "set": {"status": "in secure storage"},
         "reason": "data-bearing media flagged at receiving → Data Security log (FRM-HDD-SEC-001)"},
        {"when": ("fm", "!none"), "target": "focus_materials",
         "map": {"at": "at", "lot": "location"},
         "set": {"status": "in storage"}, "fm_from": "fm",
         "reason": "focus materials present at receiving → FM inventory (FRM-R2-FM-001)"},
        {"when": ("condition", "no*"), "target": "nonconforming",
         "map": {"lot": "item", "at": "at", "equipment": "desc"},
         "set": {"source": "receiving inspection", "status": "open"},
         "reason": "damaged / unsecured load → Nonconforming Output Control (FRM-QC-002)"},
        {"when": ("routing", "*asset control*"), "target": "wh_inbound",
         "map": {"lot": "lot", "at": "at", "equipment": "equipment"},
         "set": {"status": "registered"},
         "reason": "routed to Asset Control → asset registration started (FRM-AST-INV-001)"},
    ],
    # C · Testing & Repair (FRM-CHR-TEST-001)
    "qc": [
        {"when": ("disposition", "*spare parts*"), "target": "spare_parts",
         "map": {"serial": "asset_id", "lot": "lot", "model": "model",
                 "at": "at", "spare_loc": "location", "tech": "by"},
         "set": {"status": "in spare parts storage"},
         "reason": "unit dispositioned to Spare Parts → harvest record (FRM-SPARE-001)"},
        {"when": ("disposition", "*recycle*"), "target": "recycle_intake",
         "map": {"lot": "source_ref", "model": "desc", "at": "at", "tech": "by"},
         "set": {"status": "intake"},
         "reason": "unit dispositioned to Disposal → recycle intake (FRM-RCY-001)"},
    ],
    # C2 · Spare Parts (FRM-SPARE-001)
    "spare_parts": [
        {"when": ("transfer", "*disposal*"), "target": "recycle_intake",
         "map": {"asset_id": "source_ref", "model": "desc", "at": "at", "by": "by"},
         "set": {"source": "Disposal Area — spare parts carcasses (FRM-SPARE-001)",
                 "status": "intake"},
         "reason": "fully-harvested carcass → recycle intake (FRM-RCY-001)"},
    ],
    # J · Final QC (FRM-QC-001)
    "refurb": [
        {"when": ("decision", "reject*"), "target": "nonconforming",
         "map": {"lot": "item", "at": "at", "inspector": "verified_by"},
         "set": {"source": "final QC", "status": "open"},
         "reason": "Final QC reject → NC report (FRM-QC-002)"},
        {"when": ("decision", "release*"), "target": "outbound",
         "map": {"lot": "contents", "at": "at", "approved_by": "released_by"},
         "set": {"packing": "pending", "inspection": "pending", "status": "planned"},
         "reason": "Final QC release → shipment record started (FRM-SHP-001)"},
    ],
    # N · Calibration & Equipment Maintenance (FRM-IMS-003)
    "calibration_r2": [
        {"when": ("tolerance", "no*"), "target": "nonconforming",
         "map": {"equip_id": "item", "equipment": "desc", "at": "at", "by": "verified_by"},
         "set": {"source": "internal audit", "status": "open"},
         "reason": "equipment out of tolerance → NC report & quarantine (FRM-QC-002)"},
    ],
    # L · Safety incidents (FRM-SAF-006/007)
    "ehs_incidents": [
        {"when": ("type", "*spill*"), "target": "env_monitoring",
         "map": {"at": "at", "desc": "result"},
         "set": {"aspect": "spill containment", "compliant": "no — action required"},
         "reason": "spill incident → environmental monitoring entry (FRM-ENV-005/006)"},
    ],
    # K · Waste & Hazardous Disposal (FRM-ENV-002/003)
    "waste_disposal": [
        {"when": ("type", "hazardous*"), "target": "env_monitoring",
         "map": {"at": "at", "desc": "result"},
         "set": {"aspect": "storage integrity", "compliant": "yes"},
         "reason": "hazardous waste shipment → environmental monitoring entry (FRM-ENV-006)"},
    ],
    # J2 · Nonconforming (FRM-QC-002)
    "nonconforming": [
        {"when": ("disposition", "*spare parts*"), "target": "spare_parts",
         "map": {"item": "asset_id", "at": "at", "verified_by": "by"},
         "set": {"reason": "other", "status": "in spare parts storage"},
         "reason": "NC disposition to spare parts → harvest record (FRM-SPARE-001)"},
        {"when": ("disposition", "*recycle*"), "target": "recycle_intake",
         "map": {"item": "source_ref", "desc": "desc", "at": "at"},
         "set": {"source": "Final QC reject (FRM-QC-002)", "status": "intake"},
         "reason": "NC disposition to recycle → recycle intake (FRM-RCY-001)"},
    ],
    # J3 · Returns / RMA (FRM-QC-003)
    "returns_rma": [
        {"when": ("data_check", "*media present*"), "target": "media_security",
         "map": {"item": "source", "at": "at", "by": "by"},
         "set": {"status": "in secure storage"},
         "reason": "customer media present on return → Data Security log (FRM-HDD-SEC-001)"},
        {"when": ("disposition", "*recycle*"), "target": "recycle_intake",
         "map": {"item": "source_ref", "at": "at", "by": "by"},
         "set": {"status": "intake"},
         "reason": "return dispositioned to recycle → recycle intake (FRM-RCY-001)"},
    ],
    # D · Dismantling (FRM-DTK-DIS-001)
    "dismantling": [
        {"when": ("hdd", "!0"), "target": "media_security",
         "map": {"lot": "source", "at": "at", "tech": "by"},
         "set": {"status": "in secure storage"},
         "reason": "media removed at dismantling → Data Security log (FRM-HDD-SEC-001)"},
    ],
    # M · Recycle intake (FRM-RCY-001)
    "recycle_intake": [
        {"when": ("media_check", "*media found*"), "target": "media_security",
         "map": {"intake": "source", "at": "at", "by": "by"},
         "set": {"status": "in secure storage"},
         "reason": "media discovered during recycle intake → Data Security log (FRM-HDD-SEC-001)"},
    ],
}


def cascade_for(module: str, data: dict, valid_modules: set) -> list[dict]:
    """Related records to auto-create for a new record in `module`.
    Returns [{module, data, reason}] — only for registers that exist in the
    workspace; never raises (a cascade must not block the primary record)."""
    out: list[dict] = []
    try:
        for rule in CASCADE_RULES.get(module, []):
            field, pat = rule["when"]
            if not _match(str(data.get(field, "") or ""), pat):
                continue
            tgt = rule["target"]
            if tgt not in valid_modules or tgt == module:
                continue
            payload = dict(rule.get("set") or {})
            for src, dst in (rule.get("map") or {}).items():
                v = data.get(src)
                if v not in (None, ""):
                    payload[dst] = v
            if rule.get("fm_from"):        # focus-material type normalization
                raw = str(data.get(rule["fm_from"], "") or "").lower()
                payload["material"] = _FM_MAP.get(raw, "other")
            payload["_linked_from"] = module   # provenance marker (shown in UI)
            out.append({"module": tgt, "data": payload, "reason": rule["reason"]})
    except Exception:  # noqa: BLE001 — cascades are best-effort
        return out
    return out


# ============================================================
# Chat command engine — every ERP menu is fully controllable
# from chat prompts, in ANY language (input is pre-normalized
# by i18n_intents.normalize_intent_text, so 庫存/inventario/
# inventaire… all arrive here as English tokens).
# ============================================================
import re as _re

# module synonyms (english, post-normalization) → module key
MODULE_SYNONYMS: dict[str, str] = {
    "inventory": "inventory", "stock": "inventory", "sku": "inventory",
    "pos": "pos_sales", "sale": "pos_sales", "sales": "pos_sales",
    "receipt": "pos_sales", "order": "pos_sales",
    "customer": "customers", "crm": "customers",
    "invoice": "invoices", "bill": "invoices", "billing": "invoices",
    "quote": "quotes", "quotation": "quotes", "estimate": "quotes",
    "purchase order": "purchase_orders", "po": "purchase_orders",
    "purchase": "purchase_orders",
    "worker": "workers", "staff": "workers", "hr": "workers", "personnel": "workers",
    "employee": "workers", "enrollment": "workers",
    "injury": "hr_injury", "accident": "hr_injury", "incident": "hr_injury",
    "violation": "hr_violation", "disciplinary": "hr_violation", "discipline": "hr_violation",
    "quit": "hr_separation", "separation": "hr_separation", "resignation": "hr_separation",
    "offboarding": "hr_separation",
    "inbound": "inbound", "receiving": "inbound", "intake": "inbound",
    "putaway": "wh_inbound", "warehouse inbound": "wh_inbound",
    "outbound": "outbound", "dispatch": "outbound", "shipment out": "outbound",
    "service job": "service", "service": "service",
    "refurb": "refurb", "refurbished": "refurb",
    "qc": "qc", "quality control": "qc", "inspection": "qc", "functional test": "qc",
    "downstream": "downstream", "due diligence": "downstream",
    "focus material": "focus_materials", "battery": "focus_materials",
    "mercury": "focus_materials", "crt": "focus_materials",
    "solar panel": "focus_materials", "solar cell": "focus_materials",
    "pv module": "focus_materials", "photovoltaic": "focus_materials",
    "ehs": "ehs_incidents", "ehs incident": "ehs_incidents",
    "near miss": "ehs_incidents", "spill": "ehs_incidents",
    "monitoring": "env_monitoring", "emission": "env_monitoring",
    "environmental monitoring": "env_monitoring",
    "permit": "env_permits", "license": "env_permits",
    "sanitize": "data_sanitize", "sanitise": "data_sanitize", "wipe": "data_sanitize",
    "data sanitize": "data_sanitize",
    "dismantling": "dismantling", "dismantle": "dismantling", "teardown": "dismantling",
    "desktop dismantling": "dismantling",
    "media security": "media_security", "data bearing": "media_security",
    "secure storage": "media_security", "media log": "media_security",
    "warehouse inspection": "warehouse_inspection", "daily inspection": "warehouse_inspection",
    "housekeeping": "warehouse_inspection",
    "waste disposal": "waste_disposal", "hazardous waste": "waste_disposal",
    "waste": "waste_disposal",
    "asset registration": "wh_inbound", "asset control": "wh_inbound", "asset id": "wh_inbound",
    "chromebook": "qc", "testing and repair": "qc", "test and repair": "qc",
    "final qc": "refurb", "final inspection": "refurb", "release": "refurb",
    "receiving": "inbound", "incoming equipment": "inbound",
    "spare part": "spare_parts", "spare parts": "spare_parts", "harvest": "spare_parts",
    "locked unit": "spare_parts", "donor unit": "spare_parts",
    "recycle": "recycle_intake", "recycling": "recycle_intake",
    "recycle intake": "recycle_intake", "disposal area": "recycle_intake",
    "recycle storage": "recycle_storage", "recycle inventory": "recycle_storage",
    "downstream outbound": "recycle_outbound", "downstream shipment": "recycle_outbound",
    "management review": "mgmt_review", "objective": "objectives", "kpi": "objectives",
    "aspect": "env_aspects", "environmental aspect": "env_aspects",
    "compliance evaluation": "legal_eval", "legal compliance": "legal_eval",
    "hazard": "hazard_ja", "jha": "hazard_ja", "risk assessment": "hazard_ja",
    "drill": "emergency_drills", "emergency": "emergency_drills", "evacuation": "emergency_drills",
    "ppe": "ppe_register", "contractor": "contractors", "visitor": "contractors",
    "safety committee": "safety_committee", "consultation": "safety_committee",
    "calibration": "calibration_r2", "scale": "calibration_r2",
    "material balance": "material_balance", "throughput": "material_balance",
    "insurance": "insurance", "closure plan": "insurance",
    "complaint": "complaints_fb", "feedback": "complaints_fb",
    "supplier evaluation": "supplier_eval",
    "nonconforming": "nonconforming", "nc report": "nonconforming", "quarantine": "nonconforming",
    "secure area": "secure_access", "access log": "secure_access", "security check": "secure_access",
    "management of change": "moc", "change management": "moc", "moc": "moc",
    "communication": "communications", "notice": "communications",
    "verification sampling": "sanitize_verify", "wipe verification": "sanitize_verify",
    "sampling verification": "sanitize_verify", "spot check": "sanitize_verify",
    "rma": "returns_rma", "warranty": "returns_rma", "warranty return": "returns_rma",
    "return rma": "returns_rma", "customer return": "returns_rma", "post delivery": "returns_rma",
    "authorization matrix": "competency", "competency": "competency",
    "qualification": "competency", "authorized operator": "competency",
    "reuse evaluation": "reuse_eval", "reuse category": "reuse_eval",
    "categorization": "reuse_eval", "grading": "reuse_eval",
    "counterfeit": "brand_protect", "brand protection": "brand_protect",
    "trademark": "brand_protect", "authenticity": "brand_protect",
    "health surveillance": "health_surv", "occupational health": "health_surv",
    "noise": "health_surv", "dosimetry": "health_surv", "exposure monitoring": "health_surv",
    "frm-reu": "reuse_eval", "frm-saf-011": "health_surv", "frm-ims-010": "competency",
    "frm-qc-003": "returns_rma", "frm-data-wipe-006": "sanitize_verify",
    "verification sampling": "sanitize_verify", "wipe verification": "sanitize_verify",
    "sampling verification": "sanitize_verify", "spot check": "sanitize_verify",
    "rma": "returns_rma", "warranty": "returns_rma", "warranty return": "returns_rma",
    "return rma": "returns_rma", "customer return": "returns_rma", "post delivery": "returns_rma",
    "authorization matrix": "competency", "competency": "competency",
    "qualification": "competency", "authorized operator": "competency",
    "reuse evaluation": "reuse_eval", "reuse category": "reuse_eval",
    "categorization": "reuse_eval", "grading": "reuse_eval",
    "counterfeit": "brand_protect", "brand protection": "brand_protect",
    "trademark": "brand_protect", "authenticity": "brand_protect",
    "health surveillance": "health_surv", "occupational health": "health_surv",
    "noise": "health_surv", "dosimetry": "health_surv", "exposure monitoring": "health_surv",
    "frm-reu": "reuse_eval", "frm-saf-011": "health_surv", "frm-ims-010": "competency",
    "frm-qc-003": "returns_rma", "frm-data-wipe-006": "sanitize_verify",
    # IMS form codes → registers
    "frm-rec": "inbound", "frm-ast": "wh_inbound", "frm-chr": "qc",
    "frm-spare": "spare_parts",
    "frm-rcy-002": "recycle_storage", "frm-rcy-003": "recycle_outbound", "frm-rcy": "recycle_intake",
    "frm-ims": "mgmt_review",
    "frm-dtk": "dismantling", "frm-hdd": "media_security", "frm-data-wipe": "data_sanitize",
    "frm-r2-fm-008": "downstream", "frm-r2-fm": "focus_materials",
    "frm-whs": "warehouse_inspection", "frm-shp": "outbound",
    "frm-qc": "refurb", "frm-env": "waste_disposal", "frm-saf": "ehs_incidents",
    "data destruction": "data_sanitize", "hard drive": "data_sanitize",
    "chart of accounts": "coa", "coa": "coa", "account": "coa",
    "timesheet": "timesheets", "attendance": "timesheets", "work hours": "timesheets",
    "ledger": "ledger", "accounting": "ledger", "journal": "ledger",
    "expense": "expenses", "spending": "expenses", "cost": "expenses",
    "capa": "capa", "corrective action": "capa",
    "audit": "audits", "risk": "risks", "training": "training",
    "supplier": "supplier", "work order": "workorders", "workorder": "workorders",
    "dispatch": "dispatch", "load": "dispatch", "listing": "listings",
    "claim": "claims", "policy": "policies", "shipment": "shipments",
    "booking": "bookings", "appointment": "appts", "referral": "referrals",
    "return": "returns", "rma": "returns",
    "pallet": "inbound", "pallets": "inbound", "pallet grading": "inbound",
    "warehouse": "inbound", "incoming": "inbound", "delivery": "inbound",
    "truckload": "inbound", "truck load": "inbound",
}
_SYN_SORTED = sorted(MODULE_SYNONYMS, key=len, reverse=True)
_MOD_WORDS = "|".join(_re.escape(s) for s in _SYN_SORTED)

BUSINESS_INTENT = _re.compile(
    r"\b(?:(?:list|show|check|view|open|search|find|count|report|summary|summarize|test)\b.{0,40}\b(" + _MOD_WORDS + r")s?\b"
    r"|(?:add|create|new|record|log|register|update|revise|edit|change|modify|set|setup|set\s+up|receive[ds]?|arriv\w+|test)\b.{0,60}\b(" + _MOD_WORDS + r")s?\b"
    r"|(" + _MOD_WORDS + r")s?\b.{0,40}\b(?:list|show|report|summary|add|create|new|record|log|update|revise|edit|setup|set\s+up|test)\b"
    # logistics / arrival phrasing: "20 pallets (of X) get into the warehouse",
    # "a shipment arrived", "please arrange/put away/unload them" — workers
    # speak like this at the dock; route it to the register, not the AI.
    r"|(" + _MOD_WORDS + r")s?\b.{0,60}\b(?:arriv\w+|deliver\w+|receiv\w+|unload\w+|put\s*away|arrange\w*|came\s+in|come\s+in|get\s+in(?:to)?|got\s+in(?:to)?|check(?:ed)?\s+in)\b"
    r"|(?:arriv\w+|deliver\w+|unload\w+|incoming|put\s*away|arrange\w*)\b.{0,60}\b(" + _MOD_WORDS + r")s?\b"
    r"|(?:delete|remove|mark|complete|finish|done|paid)\b.{0,30}\b(" + _MOD_WORDS + r")s?\s*#?\d"
    r"|\b(?:business|erp)\s+(?:report|summary|overview|status)\b"
    r"|\blow\s+stock\b)", _re.I)

_KV = _re.compile(r"([A-Za-z_][A-Za-z_ ]{0,20}?)\s*[:=]\s*([^,;\n]+)")
_NUM_REF = _re.compile(r"#\s*(\d{1,4})")


def _find_module(text: str, company_type: str, user_id: "str | None" = None):
    mods = modules_for(company_type, user_id)
    keys = {m["key"]: m for m in mods}
    low = text.lower()
    # earliest mention wins (natural word order: the first register named is
    # the intended one); ties broken by longer synonym.
    best, best_pos, best_len = None, 10 ** 9, 0
    for syn in _SYN_SORTED:
        mm = _re.search(r"\b" + _re.escape(syn) + r"s?\b", low)
        if not mm:
            continue
        key = MODULE_SYNONYMS[syn]
        cand = keys.get(key)
        if cand is None:
            # industry-specific keys may differ; fuzzy match on key/name/synonym
            for m in mods:
                nm = m["name"].lower()
                if key in m["key"] or key.replace("_", " ") in nm or syn in nm:
                    cand = m
                    break
        if cand is None:
            continue
        pos = mm.start()
        if pos < best_pos or (pos == best_pos and len(syn) > best_len):
            best, best_pos, best_len = cand, pos, len(syn)
    return best


def _fmt_val(v) -> str:
    s = str(v if v is not None else "")
    return s if len(s) <= 40 else s[:38] + "…"


def _list_rows(db, user_id: str, mod: dict, limit: int = 15):
    from .db import BusinessRecord
    return (db.query(BusinessRecord)
            .filter(BusinessRecord.user_id == user_id, BusinessRecord.module == mod["key"])
            .order_by(BusinessRecord.created_at.desc()).limit(limit).all())


def biz_owner_id(db, user_id: str) -> str:
    """Tenant resolution — the company workspace is SHARED. Worker accounts
    (non-admin, provisioned by HR enrollment) do not own a commercial
    profile; they operate on the workspace of THEIR company:
    1. explicit binding (users.company_owner_id, set at HR enrollment) — on
       multi-company servers each worker sees ONLY their company's data;
    2. own commercial profile (admins / owners);
    3. legacy fallback: the first admin with a commercial profile."""
    from .db import BusinessProfile, User
    try:
        me = db.query(User).filter(User.id == user_id).first()
        if me is not None and (me.company_owner_id or "").strip():
            owner = (db.query(BusinessProfile)
                     .filter(BusinessProfile.user_id == me.company_owner_id,
                             BusinessProfile.usage_mode == "commercial").first())
            if owner:
                return me.company_owner_id
        own = (db.query(BusinessProfile)
               .filter(BusinessProfile.user_id == user_id,
                       BusinessProfile.usage_mode == "commercial").first())
        if own:
            return user_id
        row = (db.query(BusinessProfile)
               .join(User, User.id == BusinessProfile.user_id)
               .filter(BusinessProfile.usage_mode == "commercial",
                       User.is_admin.is_(True), User.deleted_at.is_(None))
               .order_by(BusinessProfile.id).first())
        return row.user_id if row else user_id
    except Exception:  # noqa: BLE001 — tenant resolution must never break a request
        return user_id


def handle_business_prompt(db, text: str, user_id: str) -> "str | None":
    """Operate ANY ERP register from a chat prompt (any language).
    Returns a reply string, or None when the prompt isn't a business op."""
    from .db import BusinessProfile, BusinessRecord
    from .security import audit as _audit
    import datetime as _dt0

    def _ts() -> str:
        from .tz import now_local
        n = now_local()
        return n.strftime("%Y-%m-%d %H:%M:%S ") + n.tzname()  # PST/PDT

    def _footer(op_code: str) -> str:
        return (f"\n\n`TXN {op_code} · {_ts()}` — committed to the tamper-evident "
                "audit chain (SHA-256 linked). Review under **Business ▸ Operation Log**.")

    user_id = biz_owner_id(db, user_id)   # workers act on the company workspace
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user_id).first()
    if not bp or bp.usage_mode != "commercial":
        return None
    low = text.lower()

    # ---- global ERP report ----
    if _re.search(r"\b(?:business|erp)\s+(?:report|summary|overview|status)\b", low):
        mods = modules_for(bp.company_type, user_id)
        counts: dict[str, list[int]] = {}
        for r in db.query(BusinessRecord.module, BusinessRecord.status) \
                   .filter(BusinessRecord.user_id == user_id).all():
            c = counts.setdefault(r[0], [0, 0])
            c[0] += 1
            if r[1] == "open":
                c[1] += 1
        lines = [f"📊 **ERP STATUS — {bp.company_name or template_label(bp.company_type, bp.custom_type)}**", ""]
        for cat in ("OPERATIONS", "SALES", "SUPPLY", "HR", "FINANCE", "COMPLIANCE"):
            group = [m for m in mods if m.get("cat") == cat]
            if not group:
                continue
            lines.append(f"__{cat}__")
            for m in group:
                c = counts.get(m["key"], [0, 0])
                lines.append(f"  {m.get('icon', '▫')} {m['name']}: {c[0]} record(s), {c[1]} open")
        return "\n".join(lines)

    # ---- low stock alert ----
    if "low stock" in low or ("inventory" in low and _re.search(r"\b(reorder|low|shortage)\b", low)):
        rows = _list_rows(db, user_id, {"key": "inventory"}, 500)
        alerts = []
        for r in rows:
            try:
                d = json.loads(r.data or "{}")
                if float(d.get("qty") or 0) <= float(d.get("reorder") or 0):
                    alerts.append(f"⚠ {d.get('name') or d.get('sku')}: {d.get('qty')} on hand (reorder at {d.get('reorder')})")
            except Exception:
                continue
        return (("📦 **INVENTORY REPLENISHMENT ADVISORY**\n\n"
                 f"{len(alerts)} SKU(s) at or below reorder threshold:\n\n"
                 + "\n".join(alerts)) if alerts
                else "✅ **INVENTORY NOMINAL** — all SKUs above their configured reorder points.")

    mod = _find_module(text, bp.company_type, user_id)
    if not mod:
        return None
    fields = [f for f in (mod.get("fields") or [])
              if (f[2] if len(f) > 2 else "") != "section"]  # markers hold no data
    cols = [f[0] for f in fields]
    label_of = {f[0]: f[1] for f in fields}

    # ---- delete / mark done / mark paid by #N ----
    mnum = _NUM_REF.search(text)
    if mnum and _re.search(r"\b(delete|remove|mark|done|complete|finish|paid|close)\b", low):
        idx = int(mnum.group(1)) - 1
        rows = _list_rows(db, user_id, mod, 100)
        if not 0 <= idx < len(rows):
            return (f"❌ **OPERATION REJECTED — {mod['name']}**\n\n"
                    f"| PARAMETER | VALUE |\n|---|---|\n"
                    f"| Requested entry | #{mnum.group(1)} |\n"
                    f"| Register size | {len(rows)} record(s) |\n"
                    f"| Disposition | No mutation performed |\n\n"
                    f"Issue `list {mod['key'].replace('_', ' ')}` to enumerate valid entry indices.")
        rec = rows[idx]
        if _re.search(r"\b(delete|remove)\b", low):
            _audit(db, f"business.{mod['key']}.delete",
                   f"entry#{idx + 1} deleted_values={rec.data or '{}'} | prompt: {text[:300]}",
                   user_id=user_id)
            db.delete(rec)
            db.commit()
            return (f"🗑 **RECORD DECOMMISSIONED — {mod['name']}**\n\n"
                    f"| PARAMETER | VALUE |\n|---|---|\n"
                    f"| Register | {mod['name']} |\n"
                    f"| Entry | #{idx + 1} |\n"
                    f"| Operation | DELETE (irreversible) |\n"
                    f"| Pre-deletion snapshot | Preserved in audit trail |"
                    + _footer(f"business.{mod['key']}.delete"))
        if "paid" in low and "status" in cols:
            d = json.loads(rec.data or "{}")
            d["status"] = "paid"
            rec.data = json.dumps(d)
        rec.status = "done"
        db.commit()
        _audit(db, f"business.{mod['key']}.status",
               f"entry#{idx + 1} marked {'paid/' if 'paid' in low else ''}done "
               f"values={rec.data or '{}'} | prompt: {text[:300]}", user_id=user_id)
        _st = ('PAID / DONE' if 'paid' in low else 'DONE')
        return (f"✅ **STATUS TRANSITION COMMITTED — {mod['name']}**\n\n"
                f"| PARAMETER | VALUE |\n|---|---|\n"
                f"| Register | {mod['name']} |\n"
                f"| Entry | #{idx + 1} |\n"
                f"| New state | {_st} |"
                + _footer(f"business.{mod['key']}.status"))

    # ---- add / create / update / revise ----
    FIELD_SYNONYMS = {
        "position": "role", "title": "role", "job": "role",
        "telephone": "phone", "tel": "phone", "mobile": "phone", "cell": "phone",
        "e-mail": "email", "mail": "email",
        "birthday": "dob", "birth date": "dob", "date of birth": "dob",
        "sex": "gender", "salary": "wage", "pay": "wage",
        "social security": "ssn", "social security number": "ssn", "tax id": "ssn",
        "tips": "tips_ratio", "tip ratio": "tips_ratio", "tips ratio": "tips_ratio",
        "tip rate": "tips_ratio", "tip %": "tips_ratio", "tips %": "tips_ratio",
        "addr": "address", "location": "address",
        "hire date": "hired", "hired date": "hired", "start date": "hired",
    }

    def _parse_kv(txt: str) -> dict:
        # line-based first: `key : value` per line keeps commas in values
        # (addresses!) and stops the module prefix from eating the first key.
        # `;` accepted as a common typo for `:` on key lines.
        pairs: list[tuple[str, str]] = []
        line_kv = _re.compile(r"^\s*([A-Za-z_][A-Za-z_ .\-%]{0,30}?)\s*[:=;]\s*(.+?)\s*$")
        for ln in txt.splitlines():
            m = line_kv.match(ln)
            if m:
                pairs.append((m.group(1), m.group(2)))
        if len(pairs) <= 1:  # single-line prompt → fall back to inline pairs
            pairs = _KV.findall(txt)
        out = {}
        for k, v in pairs:
            kl = k.strip().lower()
            k2 = FIELD_SYNONYMS.get(kl, kl).replace(" ", "_")
            hit = next((c for c in cols if c == k2
                        or label_of[c].lower().startswith(k2.replace("_", " "))
                        or label_of[c].lower().startswith(kl)), None)
            if hit:
                out[hit] = v.strip()
        return out

    # ---- update / revise an existing record by name or #N ----
    if _re.search(r"\b(update|revise|edit|change|modify|set)\b", low):
        rows = _list_rows(db, user_id, mod, 100)
        rec = None
        if mnum and 0 <= int(mnum.group(1)) - 1 < len(rows):
            rec = rows[int(mnum.group(1)) - 1]
        else:
            # match by any text value in the record (e.g. worker name)
            head = text.split(":", 1)[0].lower()
            for r in rows:
                try:
                    d = json.loads(r.data or "{}")
                except Exception:
                    continue
                nm = str(d.get(cols[0]) or "").strip().lower()
                if nm and nm in head:
                    rec = r
                    break
        if rec is None:
            return (f"❓ **TARGET RESOLUTION FAILED — {mod['name']}**\n\n"
                    f"The amendment request could not be bound to a unique record. "
                    f"No mutation was performed.\n\n"
                    f"__RECOMMENDED PROCEDURE__\n"
                    f"- `list {mod['key'].replace('_', ' ')}` — enumerate register entries\n"
                    f"- `update {mod['key'].replace('_', ' ')} #N: field=value, …` — amend by index")
        changes = _parse_kv(text)
        if not changes:
            return (f"ℹ **AMENDMENT SPECIFICATION REQUIRED — {mod['name']}**\n\n"
                    f"Provide field assignments, e.g. "
                    f"`update {mod['key'].replace('_', ' ')}: phone=…, email=…`\n\n"
                    f"__ADDRESSABLE FIELDS__\n" +
                    "\n".join(f"- {label_of[c]} (`{c}`)" for c in cols[:8]))
        d = json.loads(rec.data or "{}")
        old_vals = {k: d.get(k, "") for k in changes}
        d.update(changes)
        rec.data = json.dumps(d)
        db.commit()
        diff = "; ".join(f"{k}: '{old_vals.get(k, '')}' → '{v}'" for k, v in changes.items())
        _audit(db, f"business.{mod['key']}.update",
               f"record='{d.get(cols[0]) or '#'}' changes[{diff}] | prompt: {text[:300]}",
               user_id=user_id)
        manifest = "\n".join(
            f"| {label_of.get(k, k)} | {old_vals.get(k, '') or '—'} | {v} |"
            for k, v in changes.items())
        missing = [c for c in cols if not str(d.get(c) or "").strip()][:6]
        ask = ("\n\n__DATA COMPLETENESS ADVISORY__\nOutstanding fields: "
               + ", ".join(f"**{label_of[c]}**" for c in missing)
               if missing else "")
        return (f"✏ **RECORD AMENDED — {mod['name']}**\n"
                f"Subject: **{d.get(cols[0]) or '#'}**\n\n"
                f"__CHANGE MANIFEST__\n"
                f"| FIELD | PREVIOUS | NEW |\n|---|---|---|\n{manifest}"
                f"{ask}"
                + _footer(f"business.{mod['key']}.update"))

    if _re.search(r"\b(add|create|new|record|log|register|setup|set\s+up|receive[ds]?|arriv\w+"
                  r"|deliver\w+|unload\w+|put\s*away|arrange\w*|came\s+in|come\s+in"
                  r"|get\s+in(?:to)?|got\s+in(?:to)?|incoming)\b", low):
        data: dict = _parse_kv(text)
        if not data:
            # heuristics: quantities, money, and the remaining text into first text field
            mqty = _re.search(r"\b(?:qty|quantity|x)\s*(\d+(?:\.\d+)?)", low) or _re.search(r"\b(\d+)\s*(?:pcs|units?|kg|boxes?)\b", low)
            if mqty and "qty" in cols:
                data["qty"] = mqty.group(1)
            mmoney = _re.search(r"\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:dollars?|usd)", low)
            if mmoney:
                for c in ("amount", "total", "price", "cost", "wage"):
                    if c in cols:
                        data[c] = mmoney.group(1) or mmoney.group(2)
                        break
            # logistics heuristics: pallet counts, weights, supplier names
            mp = _re.search(r"\b(\d+(?:\.\d+)?)\s*(?:pallets?|boxes?|cartons?|skids?)\b", low)
            if mp and "pallets" in cols:
                data["pallets"] = mp.group(1)
            mw = _re.search(r"\b(\d+(?:\.\d+)?)\s*(?:kg|kgs|kilograms?|lbs?|pounds?)\b", low)
            if mw and "weight" in cols:
                data["weight"] = mw.group(1)
            msup = _re.search(
                r"\bfrom\s+(?:supplier|customer|vendor|client)?\s*([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,4})", text)
            if msup:
                sup = _re.sub(r"\s+(?:Today|Yesterday|Now)$", "", msup.group(1).strip(" .,"), flags=_re.I)
                for c in ("source", "supplier", "vendor", "customer"):
                    if c in cols:
                        data[c] = sup
                        break
            # "N pallets of <equipment>" → equipment type
            meq = _re.search(r"\b(?:pallets?|boxes?|cartons?|skids?|loads?)\s+of\s+(.{3,60}?)(?=\s+(?:get|got|arriv|deliver|from|into|to|at|for|today|yesterday)\b|[,.;]|$)", text, _re.I)
            if meq and "equipment" in cols:
                data["equipment"] = meq.group(1).strip(" .,")
            # auto-assign a traceable lot number on inbound receipts
            if "lot" in cols and "lot" not in data and data:
                from .tz import now_local as _nl
                data["lot"] = "LOT-" + _nl().strftime("%Y%m%d-%H%M%S")
            first_text = next((f[0] for f in fields if f[2] == "text"), None)
            # 1) quoted text is the strongest signal for the intended value
            mq = _re.search(r"[\"'\u201c\u201d\u2018\u2019「』『」]([^\"'\u201c\u201d\u2018\u2019「』『」]{1,80})[\"'\u201c\u201d\u2018\u2019「』『」]", text)
            if mq and first_text:
                data[first_text] = mq.group(1).strip()[:200]
            elif first_text and not data:
                # 2) free text into the first text field — strip filler words
                stripped = _re.sub(
                    r"\b(please|pls|kindly|add|create|new|record|log|register|setup|set|up|receive[ds]?|arriv\w+|get|into|store[ds]?|wait|today|a|an|the|to|in|into|for|of|now|then|and|also|too|this|have|just|jsut)\b",
                    " ", text, flags=_re.I)
                stripped = _re.sub(r"\b(" + _MOD_WORDS + r")s?\b", " ", stripped, flags=_re.I)
                # drop trailing follow-up requests ("… and ask me …", "… then tell me …")
                stripped = _re.split(r"\b(?:ask|tell|show|remind|question)\b", stripped, flags=_re.I)[0]
                stripped = _re.sub(r"\s+", " ", stripped).strip(" .,:;\"'")
                # refuse junk: too long or still contains request verbs = not a clean value
                if stripped and len(stripped) <= 60 and not _re.search(
                        r"\b(me|you|about|what|how|when|where|why)\b", stripped, _re.I):
                    data[first_text] = stripped[:200]
        if not data:
            return (f"ℹ **RECORD SPECIFICATION REQUIRED — {mod['name']}**\n\n"
                    f"Supply structured field data, e.g.\n"
                    f"`add {mod['key'].replace('_', ' ')}: " + ", ".join(f"{c}=…" for c in cols[:4]) + "`\n\n"
                    f"__REGISTER SCHEMA__\n" +
                    "\n".join(f"- {label_of[c]} (`{c}`)" for c in cols[:6]))
        import datetime as _dt
        if "at" in cols and "at" not in data:
            data["at"] = _dt.date.today().isoformat()
        rec = BusinessRecord(user_id=user_id, module=mod["key"], data=json.dumps(data))
        db.add(rec)
        db.commit()
        _audit(db, f"business.{mod['key']}.create",
               f"values={json.dumps(data)} | prompt: {text[:300]}", user_id=user_id)
        manifest = "\n".join(f"| {label_of.get(k, k)} | {v} |" for k, v in data.items())
        missing = [c for c in cols if c not in data][:6]
        followup = ""
        if missing:
            followup = ("\n\n__DATA COMPLETENESS ADVISORY__\nOutstanding fields: "
                        + ", ".join(f"**{label_of[c]}**" for c in missing)
                        + f"\nSupplement via `add {mod['key'].replace('_', ' ')}: "
                        + ", ".join(f"{c}=…" for c in missing[:3])
                        + "` or the 🏢 Business console.")
        return (f"✅ **RECORD COMMITTED — {mod['name']}**\n\n"
                f"__COMMITTED VALUES__\n"
                f"| FIELD | VALUE |\n|---|---|\n{manifest}"
                f"{followup}"
                + _footer(f"business.{mod['key']}.create"))

    # ---- list / count / report (default) ----
    rows = _list_rows(db, user_id, mod, 15)
    total = len(_list_rows(db, user_id, mod, 2000))
    if _re.search(r"\bcount\b", low):
        return (f"🔢 **REGISTER CENSUS — {mod['name']}**\n\n"
                f"| METRIC | VALUE |\n|---|---|\n"
                f"| Total records | {total} |\n"
                f"| As of | {_ts()} |")
    if not rows:
        return (f"📂 **REGISTER EMPTY — {mod['name']}**\n\n"
                f"No records are currently on file. Provision entries via chat "
                f"(`add {mod['key'].replace('_', ' ')}: field=value, …`) "
                "or through the 🏢 Business console.")
    show_cols = cols[:5]
    lines = [f"📋 **REGISTER EXTRACT — {mod['name']}**",
             f"Scope: {len(rows)} of {total} record(s) · newest first · generated {_ts()}", ""]
    for i, r in enumerate(rows, 1):
        try:
            d = json.loads(r.data or "{}")
        except Exception:
            d = {}
        cells = " · ".join(f"{label_of[c]}: {_fmt_val(d.get(c, ''))}" for c in show_cols if d.get(c) not in (None, ""))
        led = "🟢" if r.status == "done" else "⚪" if r.status == "archived" else "🟡"
        lines.append(f"{i}. {led} {cells or '(empty)'}")
    lines.append("")
    lines.append("__CONTROL DIRECTIVES__")
    lines.append(f"- `mark {mod['key'].replace('_', ' ')} #2 done` — status transition")
    lines.append(f"- `update {mod['key'].replace('_', ' ')} #N: field=value` — amend record")
    lines.append(f"- `delete {mod['key'].replace('_', ' ')} #3` — decommission record")
    return "\n".join(lines)




def generation_prompt(profile, docs_text: str) -> str:
    """The prompt sent to the AI to produce the professional company
    instruction prompt (used afterwards by every chat)."""
    label = template_label(profile.company_type, profile.custom_type)
    doc_block = ""
    if docs_text:
        doc_block = ("\n\nCOMPANY SOP / ISO DOCUMENTATION (learn these procedures and "
                     "reflect them in the instructions):\n" + docs_text[:24000])
    return (
        "You are an ISO management-system consultant. Write a professional SYSTEM "
        f"INSTRUCTION PROMPT for the AI staff of a {label} business"
        + (f" named '{profile.company_name}'" if profile.company_name else "")
        + (f". Business description: {profile.company_desc}" if profile.company_desc else ".")
        + "\n\nThe instruction prompt MUST:\n"
        "1. Define the industry domain expertise, terminology and standards the AI must apply.\n"
        "2. Embed the requirements of ISO 9001 (quality), ISO 14001 (environment), "
        "ISO 45001 (occupational health & safety) and ISO/IEC 25010 (software/service quality) "
        "as operating principles: process approach, risk-based thinking, documented information, "
        "CAPA discipline, continual improvement (PDCA).\n"
        "3. Prescribe professional communication standards for customer email, quotations and reports.\n"
        "4. Follow ISO 5807 conventions when describing procedures or flows.\n"
        "5. List the industry's typical compliance obligations and red flags to watch for.\n"
        "6. Stay under 700 words, imperative voice, numbered sections.\n"
        "Return ONLY the instruction prompt text, no preamble." + doc_block)


def fallback_prompt(profile) -> str:
    """Deterministic professional prompt used when no AI CLI is available."""
    label = template_label(profile.company_type, profile.custom_type)
    name = profile.company_name or "the company"
    mods = modules_for(profile.company_type, getattr(profile, "user_id", None))
    reg_list = "; ".join(m["name"] + f" (ISO {m['iso']})" for m in mods[:8])
    return (
        f"# {label.upper()} — OPERATING INSTRUCTIONS ({name})\n"
        f"1. DOMAIN: Act as senior {label} operations staff. Use precise industry "
        "terminology; never give vague or 'consumer-grade' answers.\n"
        "2. QUALITY (ISO 9001): apply the process approach and PDCA. Every "
        "nonconformity gets root-cause analysis and a CAPA entry with owner and due date. "
        "Verify effectiveness before closing.\n"
        "3. ENVIRONMENT (ISO 14001): identify environmental aspects of every operation; "
        "log waste, disposal and permits; prefer options that reduce impact.\n"
        "4. SAFETY (ISO 45001): hazards and near-misses are always recorded and "
        "investigated; safety concerns override schedule and cost.\n"
        "5. SERVICE/SOFTWARE QUALITY (ISO/IEC 25010): evaluate deliverables against "
        "functional suitability, reliability, performance, usability, security and maintainability.\n"
        "6. DOCUMENTED INFORMATION: reference the company registers — " + reg_list + ". "
        "Cite register entries by their IDs when reporting.\n"
        "7. PROCEDURES: when describing any workflow, use ISO 5807 flowchart conventions "
        "(terminator, process, decision, document, data).\n"
        "8. COMMUNICATION: business-grade tone, complete data (dates, quantities, "
        "references), explicit next actions and owners. Ask for clarification rather than guessing."
    )
