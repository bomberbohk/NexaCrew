# SPDX-License-Identifier: MIT
"""Multilingual prompt normalization — lets users drive email / calendar /
schedule / org operations in their own language.

Foreign intent keywords (Traditional Chinese, Simplified Chinese, Japanese,
Korean, Spanish, French, German, Portuguese, Italian…) are mapped in-place to
the English tokens the intent engines understand, while everything else —
names, subjects, addresses — is left untouched.  Replacements are padded with
spaces so the English ``\\b`` word-boundary regexes keep working next to CJK
characters."""
from __future__ import annotations

import re

# phrase → english token; matched longest-first, case-insensitive for latin
PHRASES: dict[str, str] = {
    # ---------- email nouns ----------
    "電子郵件": "email", "电子邮件": "email", "郵件": "email", "邮件": "email",
    "電郵": "email", "电邮": "email", "信箱": "mailbox", "郵箱": "mailbox",
    "邮箱": "mailbox", "收件匣": "inbox", "收件箱": "inbox", "收件夹": "inbox",
    "メール": "email", "受信トレイ": "inbox", "이메일": "email", "메일": "email",
    "받은편지함": "inbox",
    "correo electrónico": "email", "correo": "email", "bandeja de entrada": "inbox",
    "courriel": "email", "boîte de réception": "inbox",
    "e-mail": "email", "posteingang": "inbox",
    "caixa de entrada": "inbox",
    "posta in arrivo": "inbox",
    # ---------- ERP / business nouns ----------
    "庫存": "inventory", "库存": "inventory", "存貨": "inventory", "存货": "inventory",
    "在庫": "inventory", "재고": "inventory",
    "inventario": "inventory", "inventaire": "inventory", "lagerbestand": "inventory",
    "estoque": "inventory",
    "發票": "invoice", "发票": "invoice", "帳單": "invoice", "账单": "invoice",
    "請求書": "invoice", "인보이스": "invoice", "청구서": "invoice",
    "factura": "invoice", "facture": "invoice", "rechnung": "invoice",
    "fatura": "invoice", "fattura": "invoice",
    "報價": "quote", "报价": "quote", "報價單": "quote", "报价单": "quote",
    "見積": "quote", "견적": "quote", "cotización": "quote", "devis": "quote",
    "angebot": "quote", "orçamento": "quote", "preventivo": "quote",
    "客戶": "customer", "客户": "customer", "顧客": "customer", "顾客": "customer",
    "고객": "customer", "cliente": "customer", "kunde": "customer",
    "員工資料": "worker", "员工资料": "worker", "員工": "worker", "员工": "worker",
    "工人": "worker", "職員": "worker", "职员": "worker", "従業員": "worker",
    "직원": "worker", "empleado": "worker", "trabajador": "worker",
    "employé": "worker", "mitarbeiter": "worker", "funcionário": "worker",
    "dipendente": "worker",
    "工時": "timesheet", "工时": "timesheet", "考勤": "timesheet", "出勤": "timesheet",
    "打卡": "timesheet", "근태": "timesheet",
    "銷售": "sales", "销售": "sales", "收據": "receipt", "收据": "receipt",
    "売上": "sales", "매출": "sales", "venta": "sales", "vente": "sales",
    "verkauf": "sales", "venda": "sales", "vendita": "sales",
    "會計": "accounting", "会计": "accounting", "帳目": "ledger", "账目": "ledger",
    "分類帳": "ledger", "分类账": "ledger", "総勘定元帳": "ledger", "회계": "accounting",
    "contabilidad": "accounting", "comptabilité": "accounting",
    "buchhaltung": "accounting", "contabilidade": "accounting", "contabilità": "accounting",
    "開支": "expense", "开支": "expense", "支出": "expense", "費用": "expense",
    "费用": "expense", "経費": "expense", "지출": "expense",
    "gasto": "expense", "dépense": "expense", "ausgabe": "expense", "despesa": "expense",
    "採購單": "purchase order", "采购单": "purchase order", "採購": "purchase order",
    "采购": "purchase order", "發注": "purchase order", "발주": "purchase order",
    "orden de compra": "purchase order", "bon de commande": "purchase order",
    "bestellung": "purchase order", "pedido de compra": "purchase order",
    "供應商": "supplier", "供应商": "supplier", "仕入先": "supplier", "공급업체": "supplier",
    "proveedor": "supplier", "fournisseur": "supplier", "lieferant": "supplier",
    "fornecedor": "supplier", "fornitore": "supplier",
    "缺貨": "low stock", "缺货": "low stock", "低庫存": "low stock", "低库存": "low stock",
    # ---------- refurbished / recycle operations ----------
    "入庫登記": "inbound", "入库登记": "inbound", "進貨登記": "inbound", "进货登记": "inbound",
    "收料": "inbound", "進料": "inbound", "进料": "inbound", "入料": "inbound",
    "收貨": "receiving", "收货": "receiving", "到貨": "receiving", "到货": "receiving",
    "進廠": "receiving", "进厂": "receiving", "入廠": "receiving", "入厂": "receiving",
    "收到一批": "receiving", "來了一批": "receiving", "来了一批": "receiving",
    "入荷": "receiving", "入荷登録": "receiving", "입고": "receiving", "수령": "receiving",
    "recepción": "inbound", "entrada de material": "inbound", "entrada": "inbound",
    "llegó mercancía": "receiving", "recibimos": "receiving", "recibir": "receiving",
    "llegada de equipos": "receiving",
    "上架": "putaway", "入倉": "putaway", "入仓": "putaway", "倉庫入庫": "putaway", "仓库入库": "putaway",
    "almacenaje": "putaway", "ubicación en almacén": "putaway",
    "出貨": "outbound", "出货": "outbound", "出庫": "outbound", "出库": "outbound",
    "發貨": "outbound", "发货": "outbound", "派送": "outbound",
    "裝車": "outbound", "装车": "outbound", "出荷": "outbound",
    "출고": "outbound", "발송": "outbound",
    "salida": "outbound", "despacho": "outbound", "envío saliente": "outbound",
    "enviamos": "outbound",
    "品管": "qc", "品質檢驗": "qc", "质量检验": "qc", "質檢": "qc", "质检": "qc",
    "檢驗": "qc", "检验": "qc", "功能測試": "qc", "功能测试": "qc",
    "測試維修": "qc", "测试维修": "qc", "測一下": "test qc", "测一下": "test qc",
    "クロームブック": "chromebook", "크롬북": "chromebook",
    "品質検査": "qc", "品質テスト": "qc", "품질검사": "qc", "테스트": "test qc",
    "control de calidad": "qc", "inspección": "qc", "prueba funcional": "qc",
    "probar": "test qc", "revisión de calidad": "qc",
    "enseñame": "show", "enseñame": "show", "enséñame": "show",
    "翻新": "refurbished", "翻新機": "refurbished", "翻新机": "refurbished",
    "整新": "refurbished", "整修": "refurbished",
    "reacondicionado": "refurbished", "reacondicionamiento": "refurbished", "renovado": "refurbished",
    "下游供應商": "downstream", "下游供应商": "downstream", "下游廠商": "downstream",
    "下游厂商": "downstream", "下游": "downstream", "盡職調查": "due diligence", "尽职调查": "due diligence",
    "proveedor aguas abajo": "downstream", "diligencia debida": "due diligence",
    "cadena de reciclaje": "downstream",
    "重點物料": "focus material", "重点物料": "focus material", "重點材料": "focus material",
    "重点材料": "focus material", "電池": "battery", "电池": "battery",
    "水銀": "mercury", "水银": "mercury", "汞": "mercury",
    "電路板": "focus material", "电路板": "focus material",
    "materiales de enfoque": "focus material", "batería": "battery", "baterías": "battery",
    "mercurio": "mercury",
    "太陽能板": "solar panel", "太阳能板": "solar panel", "太陽能電池": "solar cell",
    "太阳能电池": "solar cell", "光伏模組": "pv module", "光伏组件": "pv module",
    "光伏板": "solar panel", "光伏": "photovoltaic",
    "panel solar": "solar panel", "paneles solares": "solar panel",
    "celda solar": "solar cell", "célula solar": "solar cell",
    "módulo fotovoltaico": "pv module", "fotovoltaico": "photovoltaic",
    "數據清除": "data sanitize", "数据清除": "data sanitize", "資料清除": "data sanitize",
    "资料清除": "data sanitize", "硬碟銷毀": "data sanitize", "硬盘销毁": "data sanitize",
    "硬碟": "hard drive", "硬盘": "hard drive", "消磁": "data sanitize",
    "borrado de datos": "data sanitize", "saneamiento de datos": "data sanitize",
    "disco duro": "hard drive", "destrucción de datos": "data sanitize",
    "工安事故": "ehs incident", "工傷": "injury", "工伤": "injury",
    "安全事故": "ehs incident", "事故": "ehs incident", "險兆": "near miss", "险兆": "near miss",
    "虛驚": "near miss", "虚惊": "near miss", "洩漏": "spill", "泄漏": "spill",
    "incidente de seguridad": "ehs incident", "casi accidente": "near miss",
    "derrame": "spill", "lesión": "injury",
    "許可證": "permit", "许可证": "permit", "執照": "license", "执照": "license",
    "牌照": "license", "permiso": "permit", "licencia": "license",
    "環境監測": "environmental monitoring", "环境监测": "environmental monitoring",
    "環保監測": "environmental monitoring", "环保监测": "environmental monitoring",
    "排放": "emission", "monitoreo ambiental": "environmental monitoring",
    "emisión": "emission", "emisiones": "emission",
    "回收": "recycle", "資源回收": "recycle", "资源回收": "recycle", "reciclaje": "recycle",
    "拆解": "dismantling", "拆機": "dismantling", "拆机": "dismantling", "拆卸": "dismantling",
    "拆了": "dismantling", "解体": "dismantling", "분해": "dismantling",
    "desmontaje": "dismantling", "desmantelamiento": "dismantling",
    "desarmar": "dismantling", "desmontar": "dismantling",
    "媒體安全": "media security", "媒体安全": "media security",
    "資料儲存媒體": "media security", "数据存储介质": "media security",
    "硬碟鎖起來": "media security", "硬盘锁起来": "media security",
    "硬碟入庫": "media security", "硬盘入库": "media security",
    "seguridad de medios": "media security", "custodia de discos": "media security",
    "倉庫檢查": "warehouse inspection", "仓库检查": "warehouse inspection",
    "每日檢查": "daily inspection", "每日检查": "daily inspection",
    "inspección de almacén": "warehouse inspection", "inspección diaria": "daily inspection",
    "廢棄物處置": "waste disposal", "废弃物处置": "waste disposal",
    "危險廢棄物": "hazardous waste", "危险废弃物": "hazardous waste", "危廢": "hazardous waste", "危废": "hazardous waste",
    "eliminación de residuos": "waste disposal", "residuos peligrosos": "hazardous waste",
    "資產登記": "asset registration", "资产登记": "asset registration",
    "registro de activos": "asset registration",
    "出貨檢驗": "final inspection", "出货检验": "final inspection",
    "最終檢驗": "final qc", "最终检验": "final qc",
    "inspección final": "final qc",
    "補貨": "low stock reorder", "补货": "low stock reorder",
    # ---------- new IMS / R2 registers (zh-TW · zh-CN · Cantonese) ----------
    "備品": "spare part", "备品": "spare part", "備件": "spare part", "备件": "spare part",
    "零件拆取": "spare part harvest", "零件拆用": "spare part harvest",
    "拆零件": "spare part harvest", "攞零件": "spare part harvest", "拆件": "spare part harvest",
    "備品區": "spare part", "备品区": "spare part", "鎖機": "locked unit", "锁机": "locked unit",
    "上鎖機器": "locked unit", "上锁机器": "locked unit", "鎖咗機": "locked unit",
    "冇電開唔到機": "no power locked unit", "開唔到機": "locked unit", "不能開機": "locked unit",
    "不能开机": "locked unit", "無法開機": "locked unit", "无法开机": "locked unit",
    "回收入庫": "recycle intake", "回收入库": "recycle intake",
    "回收收料": "recycle intake", "報廢區": "disposal area", "报废区": "disposal area",
    "廢棄區": "disposal area", "废弃区": "disposal area",
    "回收倉": "recycle storage", "回收仓": "recycle storage",
    "回收儲存": "recycle storage", "回收储存": "recycle storage",
    "回收出貨": "downstream outbound", "回收出货": "downstream outbound",
    "下游出貨": "downstream outbound", "下游出货": "downstream outbound",
    "管理審查": "management review", "管理评审": "management review", "管理層檢討": "management review",
    "目標": "objective", "目标": "objective", "指標": "kpi", "指标": "kpi", "績效": "kpi", "绩效": "kpi",
    "環境考量面": "environmental aspect", "环境因素": "environmental aspect",
    "環境衝擊": "environmental aspect", "环境影响": "environmental aspect",
    "合規評估": "compliance evaluation", "合规评估": "compliance evaluation",
    "法規遵循": "legal compliance", "法规遵循": "legal compliance", "法律合規": "legal compliance",
    "危害辨識": "hazard", "危害辨识": "hazard", "危害分析": "jha", "風險評估": "risk assessment",
    "风险评估": "risk assessment", "工作危害分析": "jha",
    "演習": "drill", "演习": "drill", "演練": "drill", "演练": "drill",
    "消防演習": "drill", "消防演习": "drill", "走火警": "drill", "疏散": "evacuation",
    "緊急應變": "emergency", "应急": "emergency", "緊急": "emergency",
    "防護具": "ppe", "防护具": "ppe", "個人防護": "ppe", "个人防护": "ppe",
    "勞保用品": "ppe", "劳保用品": "ppe", "安全眼鏡": "ppe", "手套": "ppe",
    "承攬商": "contractor", "承包商": "contractor", "外判商": "contractor", "判頭": "contractor",
    "訪客": "visitor", "访客": "visitor", "訪客登記": "visitor", "访客登记": "visitor",
    "安全委員會": "safety committee", "安全委员会": "safety committee",
    "工安會議": "safety committee", "安全会议": "safety committee",
    "校正": "calibration", "校准": "calibration", "校驗": "calibration", "校验": "calibration",
    "磅秤": "scale calibration", "地磅": "scale calibration", "校磅": "scale calibration",
    "物料平衡": "material balance", "物質流": "material balance", "物质流": "material balance",
    "進出平衡": "material balance", "进出平衡": "material balance",
    "保險": "insurance", "保险": "insurance", "關廠計畫": "closure plan", "关厂计划": "closure plan",
    "客訴": "complaint", "客诉": "complaint", "投訴": "complaint", "投诉": "complaint",
    "客戶投訴": "complaint", "客户投诉": "complaint", "意見回饋": "feedback", "意见反馈": "feedback",
    "供應商評估": "supplier evaluation", "供应商评估": "supplier evaluation",
    "供應商考核": "supplier evaluation", "供应商考核": "supplier evaluation",
    "不合格品": "nonconforming", "不良品": "nonconforming", "次品": "nonconforming",
    "唔合格": "nonconforming", "隔離區": "quarantine", "隔离区": "quarantine",
    "保安區": "secure area", "安保区": "secure area", "門禁": "access log", "门禁": "access log",
    "出入記錄": "access log", "出入记录": "access log", "出入登記": "access log",
    "變更管理": "management of change", "变更管理": "management of change",
    "工程變更": "management of change", "工程变更": "management of change",
    "溝通記錄": "communication", "沟通记录": "communication", "公告": "notice", "通告": "notice",
    "抽樣驗證": "verification sampling", "抽样验证": "verification sampling",
    "抽查": "verification sampling", "抽檢": "verification sampling", "抽检": "verification sampling",
    "退貨": "return rma", "退货": "return rma", "退機": "return rma", "退机": "return rma",
    "客戶退回": "return rma", "客户退回": "return rma", "保固": "warranty return", "保修": "warranty return",
    "授權矩陣": "authorization matrix", "授权矩阵": "authorization matrix",
    "能力認證": "competency", "能力认证": "competency", "資格認定": "competency", "资格认定": "competency",
    "崗位授權": "authorization matrix", "岗位授权": "authorization matrix",
    "再使用評估": "reuse evaluation", "再使用评估": "reuse evaluation",
    "翻新分級": "reuse evaluation", "翻新分级": "reuse evaluation", "分級": "grading", "分级": "grading",
    "仿冒": "counterfeit", "假貨": "counterfeit", "假货": "counterfeit", "冒牌": "counterfeit",
    "商標": "brand protection", "商标": "brand protection",
    "健康監測": "health surveillance", "健康监测": "health surveillance",
    "職業健康": "health surveillance", "职业健康": "health surveillance",
    "噪音檢測": "health surveillance noise", "噪音检测": "health surveillance noise",
    "體檢": "health surveillance", "体检": "health surveillance",
    # ---------- Cantonese colloquial verbs & particles ----------
    "睇下": "show", "睇吓": "show", "睇一睇": "show", "俾我睇": "show me",
    "話我知": "tell me", "點樣": "how", "喺邊": "where", "有冇": "any",
    "幫我": "please", "唔該": "please", "麻煩": "please",
    "整一張": "create", "開張單": "create", "落單": "create order", "入單": "log",
    "入咗": "logged", "入貨": "receiving", "收咗貨": "receiving", "嚟咗一批": "receiving",
    "入咗一批": "receiving", "一批貨": "receiving", "入咗貨": "receiving",
    "執嘢": "putaway", "上倉": "putaway", "擺入倉": "putaway",
    "寄出": "outbound", "出咗貨": "outbound", "送貨": "outbound",
    "整爛": "damage", "壞咗": "broken", "壞機": "broken unit", "報銷": "scrap",
    "掉咗": "delete", "剷咗": "delete", "唔要": "delete", "改咗": "change",
    "搞掂": "done", "完成咗": "done", "做咗": "done",
    "洗機": "wipe", "洗碟": "data sanitize", "抹機": "data sanitize", "抹咗": "wipe",
    "驗機": "test qc", "試機": "test qc", "檢查機": "qc", "睇機": "qc",
    "幾多部": "count", "幾多個": "count", "有幾多": "count",
    # ---------- operation / audit log ----------
    "操作日誌": "operation log", "操作日志": "operation log",
    "操作紀錄": "operation log", "操作记录": "operation log",
    "操作歷史": "operation log", "操作历史": "operation log",
    "稽核日誌": "audit log", "审计日志": "audit log",
    "稽核紀錄": "audit log", "审计记录": "audit log",
    "稽核軌跡": "audit trail", "审计轨迹": "audit trail",
    "系統日誌": "system log", "系统日志": "system log",
    "活動日誌": "activity log", "活动日志": "activity log",
    "日誌": "log", "日志": "log",
    "操作ログ": "operation log", "監査ログ": "audit log",
    "監査証跡": "audit trail", "システムログ": "system log",
    "작업 로그": "operation log", "운영 로그": "operation log",
    "감사 로그": "audit log", "감사 추적": "audit trail", "시스템 로그": "system log",
    "registro de operaciones": "operation log", "registro de auditoría": "audit log",
    "registro de auditoria": "audit log", "bitácora": "operation log",
    "bitacora": "operation log", "pista de auditoría": "audit trail",
    "journal des opérations": "operation log", "journal d'audit": "audit log",
    "piste d'audit": "audit trail", "journal d'activité": "activity log",
    "betriebsprotokoll": "operation log", "prüfprotokoll": "audit log",
    "audit-protokoll": "audit log", "aktivitätsprotokoll": "activity log",
    "registro de operações": "operation log", "trilha de auditoria": "audit trail",
    "registro delle operazioni": "operation log", "registro operazioni": "operation log",
    "registro di audit": "audit log",
    "業務報告": "business report", "业务报告": "business report",
    "營運報告": "business report", "营运报告": "business report",
    "經營狀況": "business summary", "经营状况": "business summary",
    "informe de negocio": "business report", "rapport d'activité": "business report",
    "geschäftsbericht": "business report",
    "已付款": "paid", "已付": "paid", "付款": "paid", "支付済み": "paid",
    # ---------- POS / restaurant / supermarket nouns ----------
    "菜單分類": "category", "菜单分类": "category", "分類": "category", "分类": "category",
    "菜單項目": "menu item", "菜单项目": "menu item", "菜色": "dish", "商品": "product",
    "餐點": "menu item", "餐点": "menu item",
    "選項": "option", "选项": "option", "配料": "topping",
    "用餐區": "dining zone", "用餐区": "dining zone", "桌子": "table", "桌位": "table",
    "餐桌": "table", "テーブル": "table", "테이블": "table", "mesa": "table",
    "收銀機": "kiosk", "收银机": "kiosk", "銀錢箱": "cash drawer", "钱箱": "cash drawer",
    "收据打印机": "printer", "打印機": "printer", "打印机": "printer",
    "cajón de dinero": "cash drawer", "impresora": "printer", "quiosco": "kiosk",
    "供應商發票": "vendor invoice", "供应商发票": "vendor invoice",
    "進貨單": "purchase order", "进货单": "purchase order",
    "日記帳": "journal", "日记账": "journal", "分錄": "journal entry", "分录": "journal entry",
    "損益表": "profit and loss", "捯益表": "profit and loss", "利潤表": "profit and loss",
    "資產負債表": "balance sheet", "资产负债表": "balance sheet",
    "試算表": "trial balance", "试算表": "trial balance",
    "總分類帳": "general ledger", "总分类账": "general ledger",
    "現金流量表": "cash flow", "现金流量表": "cash flow", "現金流量": "cash flow",
    "flujo de caja": "cash flow", "flujo de efectivo": "cash flow",
    "稅務報表": "tax report", "税务报表": "tax report", "報稅": "tax export", "报税": "tax export",
    "estado de resultados": "profit and loss", "balance general": "balance sheet",
    "libro mayor": "general ledger", "factura de proveedor": "vendor invoice",    "지불됨": "paid", "pagado": "paid", "payé": "paid", "bezahlt": "paid", "pago": "paid",
    # ---------- calendar nouns ----------
    "行事曆": "calendar", "日曆": "calendar", "日历": "calendar", "行程表": "calendar",
    "日程表": "calendar", "行程": "event", "日程": "event",
    "活動": "event", "活动": "event", "事件": "event",
    "約會": "appointment", "约会": "appointment", "預約": "appointment",
    "预约": "appointment", "會議": "meeting", "会议": "meeting", "開會": "meeting",
    "开会": "meeting",
    "カレンダー": "calendar", "予定": "event", "会議": "meeting",
    "캘린더": "calendar", "일정": "event", "회의": "meeting",
    "calendario": "calendar", "evento": "event", "cita": "appointment",
    "reunión": "reunion meeting", "calendrier": "calendar", "événement": "event",
    "rendez-vous": "appointment", "réunion": "meeting",
    "kalender": "calendar", "termin": "appointment", "besprechung": "meeting",
    "reunião": "meeting", "riunione": "meeting", "appuntamento": "appointment",
    # ---------- verbs: create ----------
    "新增": "add", "新建": "add", "增加": "add", "添加": "add", "建立": "create",
    "创建": "create", "創建": "create", "加入": "add", "安排": "book",
    "登記": "log", "登记": "log", "記錄": "record", "记录": "record",
    "記一筆": "log", "记一笔": "log", "寫入": "log", "写入": "log",
    "填寫": "create", "填写": "create", "開單": "create", "开单": "create",
    "錄入": "log", "录入": "log",
    "追加": "add", "作成": "create", "記録": "record", "登録": "log",
    "추가": "add", "생성": "create", "기록": "record", "등록": "log",
    "añadir": "add", "agregar": "add", "crear": "create", "apuntar": "log",
    "dar de alta": "add", "capturar": "log",
    "ajouter": "add", "créer": "create", "enregistrer": "log", "noter": "log",
    "hinzufügen": "add", "erstellen": "create", "erfassen": "log", "eintragen": "log",
    "adicionar": "add", "criar": "create", "aggiungi": "add", "creare": "create",
    "registrare": "log", "annotare": "log",
    # ---------- verbs: read / check / list ----------
    "檢查": "check", "检查": "check", "查看": "check", "查閱": "read",
    "查阅": "read", "閱讀": "read", "阅读": "read", "打開": "open", "打开": "open",
    "顯示": "show", "显示": "show", "列出": "list", "搜尋": "search",
    "搜索": "search", "尋找": "find", "寻找": "find", "有沒有": "any", "有没有": "any",
    "看一下": "show", "看看": "show", "查一下": "check", "查詢": "check", "查询": "check",
    "盤點": "list", "盘点": "list", "總覽": "summary", "总览": "summary",
    "現況": "status", "现况": "status",
    "確認": "check", "확인": "check", "읽기": "read", "읽어": "read", "열기": "open",
    "조회": "check", "보여줘": "show", "목록": "list",
    "一覧": "list", "確認して": "check", "見せて": "show",
    "revisar": "check", "leer": "read", "mostrar": "show", "buscar": "search",
    "listar": "list", "registrar": "log", "anotar": "log", "consultar": "check",
    "enseñame": "show", "quiero ver": "show", "déjame ver": "show",
    "vérifier": "check", "lire": "read", "afficher": "show", "chercher": "search",
    "prüfen": "check", "lesen": "read", "zeigen": "show", "suchen": "search",
    "verificar": "check", "ler": "read", "leggere": "read", "controlla": "check",
    # ---------- verbs: delete / cancel ----------
    "刪除": "delete", "删除": "delete", "移除": "remove", "取消": "cancel",
    "清除": "remove", "丟掉": "delete", "丢掉": "delete",
    "削除": "delete", "キャンセル": "cancel", "삭제": "delete", "취소": "cancel",
    "eliminar": "delete", "borrar": "delete", "cancelar": "cancel",
    "supprimer": "delete", "annuler": "cancel",
    "löschen": "delete", "stornieren": "cancel",
    "excluir": "delete", "eliminare": "delete", "annullare": "cancel",
    # ---------- verbs: update / move ----------
    "修改": "change", "更改": "change", "變更": "change", "变更": "change",
    "改到": "move to", "改成": "change to", "改為": "change to", "改为": "change to",
    "更新": "update", "改期": "reschedule", "延期": "postpone", "移動": "move",
    "移动": "move", "調整": "revise", "调整": "revise",
    "変更": "change", "변경": "change", "수정": "update",
    "cambiar": "change", "modificar": "update", "mover": "move",
    "modifier": "change", "déplacer": "move", "reporter": "postpone",
    "ändern": "change", "verschieben": "move",
    "alterar": "change", "modificare": "change", "spostare": "move",
    # ---------- verbs: reply / forward / send / mark ----------
    "回覆": "reply", "回复": "reply", "回信": "reply", "答覆": "reply", "答复": "reply",
    "轉發": "forward", "转发": "forward", "轉寄": "forward", "转寄": "forward",
    "傳送": "send", "发送": "send", "發送": "send", "寄": "send",
    "標記": "mark", "标记": "mark", "標示": "mark", "标示": "mark",
    "已讀": "as read", "已读": "as read", "未讀": "as unread", "未读": "as unread",
    "返信": "reply", "転送": "forward", "送信": "send",
    "답장": "reply", "전달": "forward", "보내기": "send", "읽음": "as read",
    "responder": "reply", "reenviar": "forward", "enviar": "send", "marcar": "mark",
    "répondre": "reply", "transférer": "forward", "envoyer": "send", "marquer": "mark",
    "antworten": "reply", "weiterleiten": "forward", "senden": "send",
    "markieren": "mark", "rispondere": "reply", "inoltrare": "forward",
    "inviare": "send", "encaminhar": "forward",
    # ---------- schedule words ----------
    "每天": "every day", "每日": "every day", "每週": "every week", "每周": "every week",
    "每月": "every month", "每小時": "every hour", "每小时": "every hour",
    "毎日": "every day", "毎週": "every week", "매일": "every day", "매주": "every week",
    "cada día": "every day", "cada semana": "every week", "todos los días": "every day",
    "chaque jour": "every day", "chaque semaine": "every week",
    "jeden tag": "every day", "jede woche": "every week",
    # ---------- time / date words ----------
    "今天": "today", "今日": "today", "明天": "tomorrow", "明日": "tomorrow",
    "昨天": "yesterday", "昨日": "yesterday", "今晚": "tonight", "早上": "morning",
    "上午": "am", "下午": "pm", "晚上": "pm", "中午": "noon", "半": ":30",
    "오늘": "today", "내일": "tomorrow", "어제": "yesterday",
    "hoy": "today", "mañana por": "morning", "ayer": "yesterday",
    "aujourd'hui": "today", "demain": "tomorrow", "hier": "yesterday",
    "heute": "today", "morgen": "tomorrow", "gestern": "yesterday",
    "hoje": "today", "amanhã": "tomorrow", "ontem": "yesterday",
    "oggi": "today", "domani": "tomorrow", "ieri": "yesterday",
    # ---------- weekdays ----------
    "星期一": "monday", "週一": "monday", "周一": "monday", "禮拜一": "monday", "礼拜一": "monday",
    "星期二": "tuesday", "週二": "tuesday", "周二": "tuesday", "禮拜二": "tuesday", "礼拜二": "tuesday",
    "星期三": "wednesday", "週三": "wednesday", "周三": "wednesday", "禮拜三": "wednesday", "礼拜三": "wednesday",
    "星期四": "thursday", "週四": "thursday", "周四": "thursday", "禮拜四": "thursday", "礼拜四": "thursday",
    "星期五": "friday", "週五": "friday", "周五": "friday", "禮拜五": "friday", "礼拜五": "friday",
    "星期六": "saturday", "週六": "saturday", "周六": "saturday", "禮拜六": "saturday", "礼拜六": "saturday",
    "星期日": "sunday", "星期天": "sunday", "週日": "sunday", "周日": "sunday",
    "禮拜日": "sunday", "礼拜天": "sunday",
    # ---------- email field words ----------
    "寄件人": "sender", "發件人": "sender", "发件人": "sender", "寄件者": "sender",
    "收件人": "recipient", "主旨": "subject", "主題": "subject", "主题": "subject",
    "關於": "about", "关于": "about", "地址": "address", "地點": "location",
    "地点": "location", "醫生": "doctor", "医生": "doctor",
    "差出人": "sender", "件名": "subject", "보낸사람": "sender", "제목": "subject",
    "remitente": "sender", "asunto": "subject", "expéditeur": "sender",
    "objet": "subject", "absender": "sender", "betreff": "subject",
    # ---------- misc grammar ----------
    "發過來": " sent ", "发过来": " sent ", "寄過來": " sent ", "寄过来": " sent ",
    "傳過來": " sent ", "传过来": " sent ",
    "展示出來": "show", "展示出来": "show", "顯示出來": "show", "显示出来": "show",
    "展示": "show", "列出來": "list", "列出来": "list",
    "從": "from", "从": "from", "來自": "from", "来自": "from",
    "一下": " ", "幫我": "please", "帮我": "please", "我要": "please", "我想": "please",
    "的": " ", "把": " ", "請": "please", "请": "please", "給": "to", "给": "to",
    "所有": "all", "全部": "all", "一封": "a", "這封": "the", "这封": "the",
    "那封": "the", "第": "#",
}

# longest phrases first so 電子郵件 wins over 郵件, 已讀 over 讀 …
_ORDERED = sorted(PHRASES.items(), key=lambda kv: -len(kv[0]))
_HAS_NONLATIN = re.compile(r"[^\x00-\x7f]")

# Chinese numerals for "第X封" / times like 三點
_CN_NUM = {"零": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if len(s) == 1:
        return _CN_NUM.get(s)
    if "十" in s:                    # 十一..九十九
        parts = s.split("十")
        tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def normalize_intent_text(text: str, user_phrases: "list[tuple[str, str]] | None" = None) -> str:
    """Translate foreign intent keywords to English tokens (padded with
    spaces).  Latin-alphabet languages are matched case-insensitively on
    word boundaries; CJK phrases are replaced directly.
    ``user_phrases`` — personal learned vocabulary, applied FIRST so each
    user's own wording wins over the built-in dictionary."""
    t = text
    for src, dst in sorted(user_phrases or [], key=lambda kv: -len(kv[0])):
        if not src:
            continue
        if _HAS_NONLATIN.search(src):
            if src in t:
                t = t.replace(src, f" {dst} ")
        else:
            t = re.sub(rf"(?i)(?<![\w]){re.escape(src)}(?![\w])", f" {dst} ", t)
    if _HAS_NONLATIN.search(text):
        # 下午3點 / 下午3:30 → 3pm ; 上午9點 → 9am   (before generic phrase pass)
        def _ampm(m: re.Match) -> str:
            h = int(m.group(2))
            mi = m.group(3) or ""
            ap = "pm" if m.group(1) in ("下午", "晚上") else "am"
            return f" {h}{(':' + mi) if mi else ''}{ap} "
        t = re.sub(r"(上午|下午|晚上|早上)\s*(\d{1,2})(?:[:點点时時](\d{2})?)?[點点时時分]?", _ampm, t)
        # 3點/3时 (no am/pm) → 3:00
        t = re.sub(r"(\d{1,2})[點点時时](\d{2})?分?", lambda m: f" {m.group(1)}:{m.group(2) or '00'} ", t)
        # 第三封 / 第3封 → #3
        t = re.sub(r"第\s*([0-9一二兩两三四五六七八九十]+)\s*[封個个項项則则]?",
                   lambda m: f" #{_cn_num(m.group(1)) or m.group(1)} ", t)
        # X月Y日/號 → X/Y   (2026年9月1日 → 2026-9-1 handled too)
        t = re.sub(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号]?",
                   lambda m: f" {m.group(1)}-{m.group(2)}-{m.group(3)} ", t)
        t = re.sub(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号]?",
                   lambda m: f" {m.group(1)}/{m.group(2)} ", t)
    # phrase replacements, longest first
    for src, dst in _ORDERED:
        if src in t:
            t = t.replace(src, f" {dst} ")
        elif not _HAS_NONLATIN.search(src):
            # latin phrases: case-insensitive whole-word
            t = re.sub(rf"(?i)(?<![\w]){re.escape(src)}(?![\w])", f" {dst} ", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()
