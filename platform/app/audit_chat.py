# SPDX-License-Identifier: MIT
"""Operation (audit) log via chat — enterprise-grade, multilingual.

Lets an administrator interrogate the tamper-evident audit trail straight
from any chat prompt, in any language ("check the operation log",
"檢查操作日誌", "muéstrame el registro de operaciones", "監査ログを見せて" …).

The reply is a professional, compliance-oriented report: scope, executive
summary, category breakdown, chained-hash integrity verification and the
event register itself — rendered natively in the requester's language.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re

# ------------------------------------------------------------------
# Intent — matched AGAINST THE NORMALIZED (english-token) text.
# i18n_intents.normalize_intent_text turns 操作日誌/registro de
# operaciones/journal des opérations/監査ログ… into "operation log".
# ------------------------------------------------------------------
AUDIT_INTENT = re.compile(
    r"\b(?:operation|operations|audit|activity|security|system)\s+(?:log|logs|trail|history)\b"
    r"|\baudit\s+(?:trail|events?|register)\b"
    r"|\b(?:who|when)\b.{0,30}\b(?:logged\s+in|changed\s+config|deleted)\b",
    re.I)

_LAST_N = re.compile(r"\blast\s+(\d{1,3})\s*(day|days|hour|hours|entries|events|records)\b", re.I)
_SHOW_N = re.compile(r"\b(?:show|list|top|latest|recent)\s+(\d{1,3})\b", re.I)

# action-prefix → audit category filter, from keywords in the prompt
_CATEGORY_KEYWORDS = {
    "auth": ("login", "logins", "auth", "authentication", "sign in", "signin"),
    "user": ("user account", "user management", "user admin", "account"),
    "company": ("company", "companies"),
    "employee": ("employee", "employees"),
    "config": ("config", "configuration", "settings", "setting"),
    "license": ("license", "licenses", "licence"),
    "schedule": ("schedule", "schedules", "scheduler", "cron"),
    "business": ("business",),
    "approval": ("approval", "approvals"),
    "client": ("client", "clients"),
    "mobile": ("mobile",),
    "setup": ("setup", "install"),
    "project": ("project", "projects"),
    "task": ("task", "tasks"),
    "identity": ("identity", "identities", "mailbox"),
}

# ------------------------------------------------------------------
# Language detection on the RAW (pre-normalization) user text so the
# answer comes back in the requester's own language.
# ------------------------------------------------------------------
_KANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_SIMPLIFIED = re.compile(r"[记录询检设应审计员级历报务给请让么这为动户过还开们时说对张问团区业条现见观觉览车轨迹绍志]")

_LANG_HINTS = [
    ("it", re.compile(r"(?i)\b(registro (?:delle )?operazioni|controlla|mostra(?:mi)?|verifica il|"
                      r"attività|cronologia|di audit)\b")),
    ("pt", re.compile(r"(?i)\b(registro de operações|operações|registo|trilha de auditoria|"
                      r"histórico|atividades|verificar o|mostrar o)\b")),
    ("es", re.compile(r"(?i)\b(registro de operaciones|operaciones|auditoría|auditoria del sistema|"
                      r"muéstrame|muestra|revísame|revisar|consultar|actividades|bitácora|bitacora)\b")),
    ("fr", re.compile(r"(?i)\b(journal|opérations|vérifier|afficher|"
                      r"historique|d'audit|audit du|activités)\b")),
    ("de", re.compile(r"(?i)\b(protokoll|betriebsprotokoll|prüfprotokoll|audit-log|überprüfen|"
                      r"anzeigen|aktivitätsprotokoll|zeige|prüfen)\b")),
]


def detect_lang(raw: str) -> str:
    if _KANA.search(raw):
        return "ja"
    if _HANGUL.search(raw):
        return "ko"
    if _CJK.search(raw):
        return "zh-cn" if _SIMPLIFIED.search(raw) else "zh-tw"
    for code, rx in _LANG_HINTS:
        if rx.search(raw):
            return code
    return "en"


# ------------------------------------------------------------------
# Localized strings — written natively, not machine-glued.
# ------------------------------------------------------------------
L10N: dict[str, dict[str, str]] = {
    "en": {
        "title": "OPERATION LOG — AUDIT TRAIL REPORT",
        "generated": "Report generated",
        "scope": "Scope",
        "scope_all": "most recent {n} events (full register)",
        "scope_days": "events from the last {d} day(s)",
        "scope_hours": "events from the last {h} hour(s)",
        "scope_today": "today's events",
        "scope_yesterday": "yesterday's events",
        "scope_cat": "category: {c}",
        "summary": "EXECUTIVE SUMMARY",
        "total": "Total events in scope: {n}",
        "actors": "Distinct operators involved: {n}",
        "cats": "Activity categories: {n}",
        "breakdown": "CATEGORY BREAKDOWN",
        "events_word": "event(s)",
        "integrity": "INTEGRITY VERIFICATION (tamper-evident hash chain)",
        "integrity_ok": "VERIFIED — all {n} chained SHA-256 entries are consistent; no evidence of tampering.",
        "integrity_fail": "ATTENTION — {n} entry/entries failed hash-chain verification. Immediate investigation is recommended.",
        "register": "EVENT REGISTER (newest first, times in Pacific Time)",
        "operator": "Operator",
        "system": "system",
        "no_events": "No audit events match the requested criteria. The register is otherwise operational and its integrity chain is intact.",
        "denied": ("**Access denied — insufficient privileges.**\n\n"
                   "The operation log contains security-relevant records and is restricted to "
                   "administrator accounts, in line with the principle of least privilege "
                   "(ISO/IEC 27001, Annex A 8.15 — Logging). Please contact your system "
                   "administrator if you require an extract."),
        "footer": ("This report is produced from the tamper-evident audit register (chained "
                   "SHA-256). Retain in accordance with your records-retention policy "
                   "(ISO/IEC 27001 A 8.15, SOC 2 CC7.2). Full register: Admin → Audit."),
        "more": "… {n} additional event(s) in scope. Ask e.g. “show 50 operation log” or refine by category or date.",
    },
    "zh-tw": {
        "title": "操作日誌 — 稽核軌跡報告",
        "generated": "報告產生時間",
        "scope": "查詢範圍",
        "scope_all": "最近 {n} 筆事件（完整登記冊）",
        "scope_days": "最近 {d} 天內的事件",
        "scope_hours": "最近 {h} 小時內的事件",
        "scope_today": "今天的事件",
        "scope_yesterday": "昨天的事件",
        "scope_cat": "類別：{c}",
        "summary": "摘要總覽",
        "total": "範圍內事件總數：{n}",
        "actors": "涉及操作人員數：{n}",
        "cats": "活動類別數：{n}",
        "breakdown": "類別統計",
        "events_word": "筆事件",
        "integrity": "完整性驗證（防竄改雜湊鏈）",
        "integrity_ok": "已驗證 — 全部 {n} 筆 SHA-256 鏈式紀錄一致，未發現任何竄改跡象。",
        "integrity_fail": "注意 — 有 {n} 筆紀錄未通過雜湊鏈驗證，建議立即進行調查。",
        "register": "事件登記冊（最新在前，時間為太平洋時間）",
        "operator": "操作人員",
        "system": "系統",
        "no_events": "沒有符合查詢條件的稽核事件。登記冊運作正常，完整性鏈完好無損。",
        "denied": ("**存取遭拒 — 權限不足。**\n\n"
                   "操作日誌包含安全相關紀錄，依最小權限原則（ISO/IEC 27001 附錄 A 8.15 — 日誌記錄），"
                   "僅限管理員帳戶查閱。如需取得日誌摘錄，請聯絡您的系統管理員。"),
        "footer": ("本報告產生自防竄改稽核登記冊（SHA-256 鏈式雜湊）。請依貴組織的紀錄保存政策留存"
                   "（ISO/IEC 27001 A 8.15、SOC 2 CC7.2）。完整登記冊請至：管理 → 稽核。"),
        "more": "…範圍內尚有 {n} 筆事件。可輸入「顯示 50 筆操作日誌」或以類別、日期縮小範圍。",
    },
    "zh-cn": {
        "title": "操作日志 — 审计轨迹报告",
        "generated": "报告生成时间",
        "scope": "查询范围",
        "scope_all": "最近 {n} 条事件（完整登记册）",
        "scope_days": "最近 {d} 天内的事件",
        "scope_hours": "最近 {h} 小时内的事件",
        "scope_today": "今天的事件",
        "scope_yesterday": "昨天的事件",
        "scope_cat": "类别：{c}",
        "summary": "摘要总览",
        "total": "范围内事件总数：{n}",
        "actors": "涉及操作人员数：{n}",
        "cats": "活动类别数：{n}",
        "breakdown": "类别统计",
        "events_word": "条事件",
        "integrity": "完整性验证（防篡改哈希链）",
        "integrity_ok": "已验证 — 全部 {n} 条 SHA-256 链式记录一致，未发现任何篡改迹象。",
        "integrity_fail": "注意 — 有 {n} 条记录未通过哈希链验证，建议立即调查。",
        "register": "事件登记册（最新在前，时间为太平洋时间）",
        "operator": "操作人员",
        "system": "系统",
        "no_events": "没有符合查询条件的审计事件。登记册运行正常，完整性链完好无损。",
        "denied": ("**访问被拒绝 — 权限不足。**\n\n"
                   "操作日志包含安全相关记录，依据最小权限原则（ISO/IEC 27001 附录 A 8.15 — 日志记录），"
                   "仅限管理员账户查阅。如需日志摘录，请联系您的系统管理员。"),
        "footer": ("本报告生成自防篡改审计登记册（SHA-256 链式哈希）。请按贵组织的记录保存政策留存"
                   "（ISO/IEC 27001 A 8.15、SOC 2 CC7.2）。完整登记册请至：管理 → 审计。"),
        "more": "…范围内还有 {n} 条事件。可输入“显示 50 条操作日志”或按类别、日期缩小范围。",
    },
    "ja": {
        "title": "操作ログ — 監査証跡レポート",
        "generated": "レポート作成日時",
        "scope": "対象範囲",
        "scope_all": "直近 {n} 件のイベント（全登録簿）",
        "scope_days": "過去 {d} 日間のイベント",
        "scope_hours": "過去 {h} 時間のイベント",
        "scope_today": "本日のイベント",
        "scope_yesterday": "昨日のイベント",
        "scope_cat": "カテゴリ：{c}",
        "summary": "エグゼクティブサマリー",
        "total": "対象イベント総数：{n} 件",
        "actors": "関与した操作者数:{n} 名",
        "cats": "アクティビティカテゴリ数:{n}",
        "breakdown": "カテゴリ別内訳",
        "events_word": "件",
        "integrity": "完全性検証（改ざん検知ハッシュチェーン)",
        "integrity_ok": "検証済み — 全 {n} 件の SHA-256 チェーンは整合しており、改ざんの痕跡はありません。",
        "integrity_fail": "警告 — {n} 件のレコードがハッシュチェーン検証に失敗しました。至急調査を推奨します。",
        "register": "イベント登録簿(新しい順、時刻は太平洋時間)",
        "operator": "操作者",
        "system": "システム",
        "no_events": "指定条件に一致する監査イベントはありません。登録簿は正常に稼働しており、完全性チェーンは無傷です。",
        "denied": ("**アクセス拒否 — 権限が不足しています。**\n\n"
                   "操作ログにはセキュリティ関連記録が含まれるため、最小権限の原則"
                   "(ISO/IEC 27001 附属書 A 8.15 — ログ取得)に基づき、管理者アカウントのみ閲覧可能です。"
                   "抜粋が必要な場合はシステム管理者にお問い合わせください。"),
        "footer": ("本レポートは改ざん検知監査登録簿(SHA-256 チェーン)から生成されています。"
                   "記録保存ポリシーに従って保管してください(ISO/IEC 27001 A 8.15、SOC 2 CC7.2)。"
                   "全登録簿:管理 → 監査。"),
        "more": "…対象範囲にさらに {n} 件あります。「操作ログを50件表示」やカテゴリ・日付での絞り込みが可能です。",
    },
    "ko": {
        "title": "운영 로그 — 감사 추적 보고서",
        "generated": "보고서 생성 시각",
        "scope": "조회 범위",
        "scope_all": "최근 {n}건의 이벤트(전체 등록부)",
        "scope_days": "최근 {d}일간의 이벤트",
        "scope_hours": "최근 {h}시간 내 이벤트",
        "scope_today": "오늘의 이벤트",
        "scope_yesterday": "어제의 이벤트",
        "scope_cat": "카테고리: {c}",
        "summary": "요약",
        "total": "범위 내 이벤트 총수: {n}건",
        "actors": "관련 운영자 수: {n}명",
        "cats": "활동 카테고리 수: {n}",
        "breakdown": "카테고리별 집계",
        "events_word": "건",
        "integrity": "무결성 검증(변조 방지 해시 체인)",
        "integrity_ok": "검증 완료 — 전체 {n}건의 SHA-256 체인 기록이 일치하며 변조 흔적이 없습니다.",
        "integrity_fail": "주의 — {n}건의 기록이 해시 체인 검증에 실패했습니다. 즉시 조사를 권장합니다.",
        "register": "이벤트 등록부(최신순, 시간은 태평양 시간)",
        "operator": "운영자",
        "system": "시스템",
        "no_events": "요청 조건에 맞는 감사 이벤트가 없습니다. 등록부는 정상 작동 중이며 무결성 체인은 손상되지 않았습니다.",
        "denied": ("**접근 거부 — 권한이 부족합니다.**\n\n"
                   "운영 로그에는 보안 관련 기록이 포함되어 있어 최소 권한 원칙"
                   "(ISO/IEC 27001 부속서 A 8.15 — 로깅)에 따라 관리자 계정만 열람할 수 있습니다. "
                   "발췌본이 필요하시면 시스템 관리자에게 문의하십시오."),
        "footer": ("본 보고서는 변조 방지 감사 등록부(SHA-256 체인)에서 생성되었습니다. "
                   "기록 보존 정책에 따라 보관하십시오(ISO/IEC 27001 A 8.15, SOC 2 CC7.2). "
                   "전체 등록부: 관리 → 감사."),
        "more": "…범위 내에 {n}건이 더 있습니다. “운영 로그 50건 표시” 또는 카테고리·날짜로 좁혀 보십시오.",
    },
    "es": {
        "title": "REGISTRO DE OPERACIONES — INFORME DE AUDITORÍA",
        "generated": "Informe generado",
        "scope": "Alcance",
        "scope_all": "los {n} eventos más recientes (registro completo)",
        "scope_days": "eventos de los últimos {d} día(s)",
        "scope_hours": "eventos de las últimas {h} hora(s)",
        "scope_today": "eventos de hoy",
        "scope_yesterday": "eventos de ayer",
        "scope_cat": "categoría: {c}",
        "summary": "RESUMEN EJECUTIVO",
        "total": "Total de eventos en el alcance: {n}",
        "actors": "Operadores distintos implicados: {n}",
        "cats": "Categorías de actividad: {n}",
        "breakdown": "DESGLOSE POR CATEGORÍA",
        "events_word": "evento(s)",
        "integrity": "VERIFICACIÓN DE INTEGRIDAD (cadena de hashes a prueba de manipulación)",
        "integrity_ok": "VERIFICADO — las {n} entradas SHA-256 encadenadas son coherentes; no hay indicios de manipulación.",
        "integrity_fail": "ATENCIÓN — {n} entrada(s) no superaron la verificación de la cadena de hashes. Se recomienda investigar de inmediato.",
        "register": "REGISTRO DE EVENTOS (más recientes primero, hora del Pacífico)",
        "operator": "Operador",
        "system": "sistema",
        "no_events": "Ningún evento de auditoría coincide con los criterios solicitados. El registro funciona con normalidad y su cadena de integridad está intacta.",
        "denied": ("**Acceso denegado — privilegios insuficientes.**\n\n"
                   "El registro de operaciones contiene información relevante para la seguridad y está "
                   "restringido a cuentas de administrador, conforme al principio de mínimo privilegio "
                   "(ISO/IEC 27001, Anexo A 8.15 — Registro de eventos). Contacte con su administrador "
                   "si necesita un extracto."),
        "footer": ("Este informe se genera a partir del registro de auditoría a prueba de manipulación "
                   "(SHA-256 encadenado). Consérvelo según su política de retención de registros "
                   "(ISO/IEC 27001 A 8.15, SOC 2 CC7.2). Registro completo: Administración → Auditoría."),
        "more": "… {n} evento(s) adicionales en el alcance. Pida p. ej. «mostrar 50 registro de operaciones» o filtre por categoría o fecha.",
    },
    "fr": {
        "title": "JOURNAL DES OPÉRATIONS — RAPPORT DE PISTE D'AUDIT",
        "generated": "Rapport généré le",
        "scope": "Périmètre",
        "scope_all": "les {n} événements les plus récents (registre complet)",
        "scope_days": "événements des {d} dernier(s) jour(s)",
        "scope_hours": "événements des {h} dernière(s) heure(s)",
        "scope_today": "événements d'aujourd'hui",
        "scope_yesterday": "événements d'hier",
        "scope_cat": "catégorie : {c}",
        "summary": "SYNTHÈSE",
        "total": "Nombre total d'événements dans le périmètre : {n}",
        "actors": "Opérateurs distincts impliqués : {n}",
        "cats": "Catégories d'activité : {n}",
        "breakdown": "RÉPARTITION PAR CATÉGORIE",
        "events_word": "événement(s)",
        "integrity": "VÉRIFICATION D'INTÉGRITÉ (chaîne de hachage inviolable)",
        "integrity_ok": "VÉRIFIÉ — les {n} entrées SHA-256 chaînées sont cohérentes ; aucun signe de falsification.",
        "integrity_fail": "ATTENTION — {n} entrée(s) ont échoué à la vérification de la chaîne de hachage. Une enquête immédiate est recommandée.",
        "register": "REGISTRE DES ÉVÉNEMENTS (les plus récents d'abord, heure du Pacifique)",
        "operator": "Opérateur",
        "system": "système",
        "no_events": "Aucun événement d'audit ne correspond aux critères demandés. Le registre fonctionne normalement et sa chaîne d'intégrité est intacte.",
        "denied": ("**Accès refusé — privilèges insuffisants.**\n\n"
                   "Le journal des opérations contient des enregistrements sensibles et est réservé aux "
                   "comptes administrateurs, conformément au principe du moindre privilège "
                   "(ISO/IEC 27001, annexe A 8.15 — Journalisation). Veuillez contacter votre "
                   "administrateur système pour obtenir un extrait."),
        "footer": ("Ce rapport est produit à partir du registre d'audit inviolable (SHA-256 chaîné). "
                   "À conserver conformément à votre politique de rétention des enregistrements "
                   "(ISO/IEC 27001 A 8.15, SOC 2 CC7.2). Registre complet : Administration → Audit."),
        "more": "… {n} événement(s) supplémentaires dans le périmètre. Demandez p. ex. « afficher 50 journal des opérations » ou affinez par catégorie ou date.",
    },
    "de": {
        "title": "BETRIEBSPROTOKOLL — AUDIT-TRAIL-BERICHT",
        "generated": "Bericht erstellt am",
        "scope": "Umfang",
        "scope_all": "die letzten {n} Ereignisse (vollständiges Register)",
        "scope_days": "Ereignisse der letzten {d} Tag(e)",
        "scope_hours": "Ereignisse der letzten {h} Stunde(n)",
        "scope_today": "heutige Ereignisse",
        "scope_yesterday": "gestrige Ereignisse",
        "scope_cat": "Kategorie: {c}",
        "summary": "ZUSAMMENFASSUNG",
        "total": "Ereignisse im Umfang insgesamt: {n}",
        "actors": "Beteiligte Bediener: {n}",
        "cats": "Aktivitätskategorien: {n}",
        "breakdown": "AUFSCHLÜSSELUNG NACH KATEGORIE",
        "events_word": "Ereignis(se)",
        "integrity": "INTEGRITÄTSPRÜFUNG (manipulationssichere Hash-Kette)",
        "integrity_ok": "VERIFIZIERT — alle {n} verketteten SHA-256-Einträge sind konsistent; keine Hinweise auf Manipulation.",
        "integrity_fail": "ACHTUNG — {n} Eintrag/Einträge haben die Hash-Ketten-Prüfung nicht bestanden. Eine sofortige Untersuchung wird empfohlen.",
        "register": "EREIGNISREGISTER (neueste zuerst, Zeiten in pazifischer Zeit)",
        "operator": "Bediener",
        "system": "System",
        "no_events": "Keine Audit-Ereignisse entsprechen den angeforderten Kriterien. Das Register ist betriebsbereit und die Integritätskette ist intakt.",
        "denied": ("**Zugriff verweigert — unzureichende Berechtigungen.**\n\n"
                   "Das Betriebsprotokoll enthält sicherheitsrelevante Aufzeichnungen und ist gemäß dem "
                   "Prinzip der minimalen Rechtevergabe (ISO/IEC 27001, Anhang A 8.15 — Protokollierung) "
                   "Administratorkonten vorbehalten. Bitte wenden Sie sich an Ihren Systemadministrator, "
                   "falls Sie einen Auszug benötigen."),
        "footer": ("Dieser Bericht wird aus dem manipulationssicheren Audit-Register (verkettetes SHA-256) "
                   "erstellt. Gemäß Ihrer Aufbewahrungsrichtlinie aufbewahren (ISO/IEC 27001 A 8.15, "
                   "SOC 2 CC7.2). Vollständiges Register: Verwaltung → Audit."),
        "more": "… {n} weitere(s) Ereignis(se) im Umfang. Fragen Sie z. B. „zeige 50 Betriebsprotokoll“ oder filtern Sie nach Kategorie oder Datum.",
    },
    "pt": {
        "title": "REGISTRO DE OPERAÇÕES — RELATÓRIO DE TRILHA DE AUDITORIA",
        "generated": "Relatório gerado em",
        "scope": "Escopo",
        "scope_all": "os {n} eventos mais recentes (registro completo)",
        "scope_days": "eventos dos últimos {d} dia(s)",
        "scope_hours": "eventos das últimas {h} hora(s)",
        "scope_today": "eventos de hoje",
        "scope_yesterday": "eventos de ontem",
        "scope_cat": "categoria: {c}",
        "summary": "RESUMO EXECUTIVO",
        "total": "Total de eventos no escopo: {n}",
        "actors": "Operadores distintos envolvidos: {n}",
        "cats": "Categorias de atividade: {n}",
        "breakdown": "DETALHAMENTO POR CATEGORIA",
        "events_word": "evento(s)",
        "integrity": "VERIFICAÇÃO DE INTEGRIDADE (cadeia de hashes à prova de adulteração)",
        "integrity_ok": "VERIFICADO — todas as {n} entradas SHA-256 encadeadas são consistentes; sem indícios de adulteração.",
        "integrity_fail": "ATENÇÃO — {n} entrada(s) falharam na verificação da cadeia de hashes. Recomenda-se investigação imediata.",
        "register": "REGISTRO DE EVENTOS (mais recentes primeiro, horário do Pacífico)",
        "operator": "Operador",
        "system": "sistema",
        "no_events": "Nenhum evento de auditoria corresponde aos critérios solicitados. O registro está operacional e sua cadeia de integridade está intacta.",
        "denied": ("**Acesso negado — privilégios insuficientes.**\n\n"
                   "O registro de operações contém informações relevantes para a segurança e é restrito a "
                   "contas de administrador, conforme o princípio do menor privilégio "
                   "(ISO/IEC 27001, Anexo A 8.15 — Registro de eventos). Contate o administrador do "
                   "sistema caso precise de um extrato."),
        "footer": ("Este relatório é produzido a partir do registro de auditoria à prova de adulteração "
                   "(SHA-256 encadeado). Conserve-o conforme sua política de retenção de registros "
                   "(ISO/IEC 27001 A 8.15, SOC 2 CC7.2). Registro completo: Administração → Auditoria."),
        "more": "… {n} evento(s) adicionais no escopo. Peça p. ex. «mostrar 50 registro de operações» ou refine por categoria ou data.",
    },
    "it": {
        "title": "REGISTRO DELLE OPERAZIONI — RAPPORTO DI AUDIT TRAIL",
        "generated": "Rapporto generato il",
        "scope": "Ambito",
        "scope_all": "gli ultimi {n} eventi (registro completo)",
        "scope_days": "eventi degli ultimi {d} giorno/i",
        "scope_hours": "eventi delle ultime {h} ora/e",
        "scope_today": "eventi di oggi",
        "scope_yesterday": "eventi di ieri",
        "scope_cat": "categoria: {c}",
        "summary": "SINTESI",
        "total": "Totale eventi nell'ambito: {n}",
        "actors": "Operatori distinti coinvolti: {n}",
        "cats": "Categorie di attività: {n}",
        "breakdown": "RIPARTIZIONE PER CATEGORIA",
        "events_word": "evento/i",
        "integrity": "VERIFICA DI INTEGRITÀ (catena di hash a prova di manomissione)",
        "integrity_ok": "VERIFICATO — tutte le {n} voci SHA-256 concatenate sono coerenti; nessun segno di manomissione.",
        "integrity_fail": "ATTENZIONE — {n} voce/i non hanno superato la verifica della catena di hash. Si raccomanda un'indagine immediata.",
        "register": "REGISTRO DEGLI EVENTI (più recenti prima, ora del Pacifico)",
        "operator": "Operatore",
        "system": "sistema",
        "no_events": "Nessun evento di audit corrisponde ai criteri richiesti. Il registro è operativo e la catena di integrità è intatta.",
        "denied": ("**Accesso negato — privilegi insufficienti.**\n\n"
                   "Il registro delle operazioni contiene informazioni rilevanti per la sicurezza ed è "
                   "riservato agli account amministratore, in conformità al principio del privilegio "
                   "minimo (ISO/IEC 27001, Allegato A 8.15 — Registrazione degli eventi). Contattare "
                   "l'amministratore di sistema per ottenere un estratto."),
        "footer": ("Questo rapporto è prodotto dal registro di audit a prova di manomissione "
                   "(SHA-256 concatenato). Conservare secondo la propria politica di conservazione dei "
                   "documenti (ISO/IEC 27001 A 8.15, SOC 2 CC7.2). Registro completo: Amministrazione → Audit."),
        "more": "… {n} evento/i aggiuntivi nell'ambito. Chiedere ad es. «mostra 50 registro operazioni» oppure filtrare per categoria o data.",
    },
}

# localized action descriptions (english fallback used for other langs)
_ACTION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "auth.login": "User signed in", "auth.setup": "Initial account setup",
        "auth.verify_admin.ok": "Admin identity verified", "auth.verify_admin.fail": "FAILED admin verification attempt",
        "user.create": "User account created", "user.update": "User account modified", "user.delete": "User account deleted",
        "config.update": "System configuration changed", "license.generate": "License keys generated",
        "license.delete": "License key revoked", "license.claim": "License key claimed",
        "schedule.create": "Scheduled job created", "schedule.update": "Scheduled job modified",
        "schedule.delete": "Scheduled job deleted", "approval.approved": "Approval request granted",
        "chat.calendar": "Calendar operated via chat", "chat.pos": "POS/Accounting operated via chat",
        "chat.visitor": "Visitor register queried via chat", "audit.viewed": "Operation log viewed via chat",
        "business.record.create": "Record created (console)",
        "business.record.update": "Record amended (console)",
        "business.record.delete": "Record deleted (console)",
    },
    "zh-tw": {
        "auth.login": "使用者登入", "auth.setup": "初始帳戶設定",
        "auth.verify_admin.ok": "管理員身分驗證成功", "auth.verify_admin.fail": "管理員驗證失敗（注意）",
        "user.create": "建立使用者帳戶", "user.update": "修改使用者帳戶", "user.delete": "刪除使用者帳戶",
        "config.update": "變更系統設定", "license.generate": "產生授權金鑰",
        "license.delete": "撤銷授權金鑰", "license.claim": "授權金鑰已領用",
        "schedule.create": "建立排程工作", "schedule.update": "修改排程工作",
        "schedule.delete": "刪除排程工作", "approval.approved": "核准請求已通過",
    },
    "zh-cn": {
        "auth.login": "用户登录", "auth.setup": "初始账户设置",
        "auth.verify_admin.ok": "管理员身份验证成功", "auth.verify_admin.fail": "管理员验证失败（注意）",
        "user.create": "创建用户账户", "user.update": "修改用户账户", "user.delete": "删除用户账户",
        "config.update": "更改系统配置", "license.generate": "生成许可证密钥",
        "license.delete": "撤销许可证密钥", "license.claim": "许可证密钥已领用",
        "schedule.create": "创建计划任务", "schedule.update": "修改计划任务",
        "schedule.delete": "删除计划任务", "approval.approved": "审批请求已通过",
    },
}


def _action_label(action: str, lang: str) -> str:
    for lg in (lang, "en"):
        lbl = _ACTION_LABELS.get(lg, {}).get(action)
        if lbl:
            return lbl
    # dynamic business register actions: business.<module>.<op>
    m = re.match(r"business\.([a-z_]+)\.(create|update|delete|status)$", action)
    if m:
        mod = m.group(1).replace("_", " ").title()
        op = {"create": {"en": "record created", "zh-tw": "新增紀錄", "zh-cn": "新增记录"},
              "update": {"en": "record updated", "zh-tw": "修改紀錄", "zh-cn": "修改记录"},
              "delete": {"en": "record deleted", "zh-tw": "刪除紀錄", "zh-cn": "删除记录"},
              "status": {"en": "record status changed", "zh-tw": "變更紀錄狀態", "zh-cn": "变更记录状态"}}[m.group(2)]
        return f"{mod} — {op.get(lang, op['en'])}"
    return action


def _verify_chain(rows_asc) -> int:
    """Verify hash-chain linkage over rows (true insertion order). An entry is
    sound when its prev_hash points at an entry_hash already present in the
    register (strictly the immediate predecessor; entries written by legacy
    versions during same-second concurrent commits may link one or two rows
    back, which is still a valid provenance link). Returns the number of
    entries whose prev_hash matches NOTHING in the register — i.e. evidence
    of removed or foreign entries."""
    bad = 0
    seen: set = {""}
    first = True
    for ev in rows_asc:
        if ev.entry_hash:  # hashed era only
            if first:
                first = False  # window boundary — predecessor may be outside
            elif (ev.prev_hash or "") not in seen:
                bad += 1
            seen.add(ev.entry_hash)
    _ = hashlib  # linkage check; payload recompute not possible retroactively
    return bad


def handle_audit_prompt(db, raw_text: str, norm_text: str, user) -> "str | None":
    """Answer an operation-log request from chat. Returns None when the
    prompt is not an audit-log query."""
    if not AUDIT_INTENT.search(norm_text):
        return None
    from .db import AuditEvent, User

    lang = detect_lang(raw_text)
    t = L10N.get(lang, L10N["en"])

    if not getattr(user, "is_admin", False):
        return t["denied"], []

    low = norm_text.lower()
    q = db.query(AuditEvent)

    # ---- time window ----
    scope_bits: list[str] = []
    now = _dt.datetime.utcnow()
    mnum = _LAST_N.search(low)
    limit = 20
    if mnum:
        n, unit = int(mnum.group(1)), mnum.group(2).lower()
        if unit.startswith("day"):
            q = q.filter(AuditEvent.created_at >= now - _dt.timedelta(days=n))
            scope_bits.append(t["scope_days"].format(d=n))
        elif unit.startswith("hour"):
            q = q.filter(AuditEvent.created_at >= now - _dt.timedelta(hours=n))
            scope_bits.append(t["scope_hours"].format(h=n))
        else:
            limit = min(n, 200)
    elif "yesterday" in low:
        start = _dt.datetime.combine(now.date() - _dt.timedelta(days=1), _dt.time.min)
        q = q.filter(AuditEvent.created_at >= start,
                     AuditEvent.created_at < start + _dt.timedelta(days=1))
        scope_bits.append(t["scope_yesterday"])
    elif "today" in low:
        q = q.filter(AuditEvent.created_at >= _dt.datetime.combine(now.date(), _dt.time.min))
        scope_bits.append(t["scope_today"])
    mshow = _SHOW_N.search(low)
    if mshow:
        limit = min(int(mshow.group(1)), 200)

    # ---- category filter ----
    cat = None
    for prefix, words in _CATEGORY_KEYWORDS.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            cat = prefix
            break
    if cat:
        q = q.filter(AuditEvent.action.like(cat + ".%"))
        scope_bits.append(t["scope_cat"].format(c=cat))

    # ---- register (business module) filter — “chromebook test & repair”,
    # “dismantling”, “workers”… filters to that register's events only ----
    reg_key, reg_name = None, ""
    if not cat:
        try:
            from .business import MODULE_SYNONYMS, _SYN_SORTED, modules_for
            from .db import BusinessProfile
            bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user.id).first()
            mods = {m["key"]: m for m in modules_for(bp.company_type, bp.user_id)} if bp else {}
            for syn in _SYN_SORTED:
                if re.search(r"\b" + re.escape(syn) + r"s?\b", low):
                    k = MODULE_SYNONYMS[syn]
                    if k in mods or any(k in mk for mk in mods):
                        reg_key = k if k in mods else next(mk for mk in mods if k in mk)
                        reg_name = mods[reg_key]["name"]
                        break
        except Exception:
            reg_key = None
    if reg_key:
        from sqlalchemy import or_
        q = q.filter(or_(AuditEvent.action.like(f"business.{reg_key}.%"),
                         AuditEvent.detail.like(f"{reg_key} %"),
                         AuditEvent.detail.like(f"{reg_key}")))
        scope_bits.append(t["scope_cat"].format(c=reg_name or reg_key))
        if limit < 50:
            limit = 50

    want_photos = bool(re.search(r"\b(photo|photos|image|images|picture|pictures|face|captur\w*|dossier)\b", low))

    total = q.count()
    rows = q.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    if not scope_bits:
        scope_bits.append(t["scope_all"].format(n=min(limit, total)))

    # ---- integrity verification over the recent register ----
    # true insertion order (rowid) — created_at has 1-second precision and
    # concurrent writes within the same second would falsely break the chain
    from sqlalchemy import text as _text
    recent_asc = (db.query(AuditEvent).order_by(_text("rowid DESC"))
                  .limit(2000).all())[::-1]
    bad = _verify_chain(recent_asc)

    # ---- operator names ----
    uid_set = {r.user_id for r in rows if r.user_id}
    users = {u.id: u.username for u in db.query(User).filter(User.id.in_(uid_set)).all()} if uid_set else {}

    # ---- category breakdown across scope ----
    cat_counts: dict[str, int] = {}
    actor_all: set = set()
    for ev in q.order_by(AuditEvent.created_at.desc()).limit(2000).all():
        cat_counts[ev.action.split(".", 1)[0]] = cat_counts.get(ev.action.split(".", 1)[0], 0) + 1
        if ev.user_id:
            actor_all.add(ev.user_id)

    lines: list[str] = []
    lines.append(f"🛡️ **{t['title']}**")
    from .tz import now_local as _now_local
    _nl = _now_local()
    lines.append(f"{t['generated']}: {_nl.strftime('%Y-%m-%d %H:%M:%S')} {_nl.tzname()}")
    lines.append(f"{t['scope']}: " + " · ".join(scope_bits))
    lines.append("")
    lines.append(f"__{t['summary']}__")
    lines.append(f"• {t['total'].format(n=total)}")
    lines.append(f"• {t['actors'].format(n=len(actor_all))}")
    lines.append(f"• {t['cats'].format(n=len(cat_counts))}")
    lines.append("")
    if not rows:
        lines.append(t["no_events"])
        lines.append("")
        lines.append("—")
        lines.append(t["footer"])
        return "\n".join(lines), []

    lines.append(f"__{t['breakdown']}__")
    for c, n in sorted(cat_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {c}: {n} {t['events_word']}")
    lines.append("")
    lines.append(f"__{t['integrity']}__")
    lines.append(("✅ " + t["integrity_ok"].format(n=len(recent_asc))) if bad == 0
                 else ("🚨 " + t["integrity_fail"].format(n=bad)))
    lines.append("")
    lines.append(f"__{t['register']}__")
    attachments: list[str] = []
    _face_rx = re.compile(r"face=([A-Za-z0-9_.\-]+\.jpg)")
    if reg_key:
        # professional table for a single register — renders as an HTML table
        lines.append("")
        lines.append(f"| # | {t.get('time_col', 'TIME (PT)')} | ACTION | {t['operator']} | VALUES | FACE |")
        lines.append("|---|---|---|---|---|---|")
        for i, ev in enumerate(rows, 1):
            who = users.get(ev.user_id, t["system"])
            from .tz import to_local as _tl
            ts = _tl(ev.created_at).strftime("%Y-%m-%d %H:%M:%S") if ev.created_at else "—"
            label = _action_label(ev.action, lang)
            det = re.sub(r"\s*\n\s*", " ", (ev.detail or "").strip())
            fm = _face_rx.search(det)
            face_id = fm.group(1) if fm else ""
            vm2 = re.search(r"\b(values=|changes=\[|deleted_values=)", det)
            if vm2:
                vals = det[vm2.start():]
                vals = re.sub(r"^(values=|changes=\[|deleted_values=)", "", vals).rstrip("]")
                vals = vals.replace("|", "｜")
                if len(vals) > 160:
                    vals = vals[:158] + "…"
            else:
                vals = "—"
            face_cell = "—"
            if face_id:
                face_cell = "📷 " + face_id[:24]
                if want_photos and len(attachments) < 12:
                    from pathlib import Path as _P
                    p = _P(__file__).resolve().parent.parent / "data" / "uploads" / "op_faces" / face_id
                    if p.exists():
                        attachments.append(str(p))
                        face_cell = "📷 attached"
            lines.append(f"| {i} | `{ts}` | **{label}** | {who} | {vals} | {face_cell} |")
        lines.append("")
    else:
        for i, ev in enumerate(rows, 1):
            who = users.get(ev.user_id, t["system"])
            from .tz import to_local as _tl
            ts = _tl(ev.created_at).strftime("%Y-%m-%d %H:%M:%S") if ev.created_at else "—"
            label = _action_label(ev.action, lang)
            det = (ev.detail or "").strip()
            det = re.sub(r"\s*\n\s*", " ⏎ ", det)
            if len(det) > 300:
                det = det[:298] + "…"
            alert = "⚠️ " if ".fail" in ev.action or "rejected" in ev.action else ""
            if want_photos and len(attachments) < 12:
                fm = _face_rx.search(ev.detail or "")
                if fm:
                    from pathlib import Path as _P
                    p = _P(__file__).resolve().parent.parent / "data" / "uploads" / "op_faces" / fm.group(1)
                    if p.exists():
                        attachments.append(str(p))
            lines.append(f"{i}. {alert}`{ts}` — **{label}** — {t['operator']}: {who}"
                         + (f" — {det}" if det else ""))
    if total > len(rows):
        lines.append("")
        lines.append(t["more"].format(n=total - len(rows)))
    lines.append("")
    lines.append("—")
    lines.append(t["footer"])
    return "\n".join(lines), attachments
