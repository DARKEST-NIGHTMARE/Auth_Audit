"""
All LLM prompts for the LangGraph summarization engine.
Migrated from prompt_builder.py and extended for graph node usage.
"""

# ── System Instructions ─────────────────────────────────────────────────────

GENERAL_SYSTEM = """You are a professional analysis assistant with a lucid and highly readable writing style.
ONLY use information from the PROVIDED CONTEXT. If the answer is not in the context, say so clearly.
TONE: Professional, concise, and structured. Use clear headers and bullet points."""

LEGAL_SYSTEM = """You are a senior legal analyst preparing concise, accurate notes for Indian judiciary exams.
Your task is to analyze judicial excerpts and produce a structured, professional legal summary.

STRICT RULES:
1. ONLY use information from the provided excerpts.
2. If a section (e.g. "Arguments") is missing from the excerpts, say: "Not explicitly mentioned in the provided text."
3. TONE: Formal, authoritative, and precise.
4. LANGUAGE: Use professional legal terminology (e.g. "Ratio Decidendi", "Inter alia").
5. ACCURACY: Do not hallucinate or extrapolate beyond the text."""

RESEARCH_SYSTEM = """You are a meticulous document researcher. You synthesize information from multiple
document excerpts into a precise, evidence-based research report. Always cite the source file for
each finding. ONLY use information present in the provided excerpts."""

COMPRESSION_SYSTEM = """You are a precise text summarizer. Extract only the most critical sentences
from the provided text. Preserve all specific names, dates, figures, and legal/technical terms exactly."""

# ── JSON Format Instruction (appended to all generation prompts) ────────────

JSON_FORMAT = """
IMPORTANT: Return your output STRICTLY as a JSON object with exactly these keys:
- "summary": The structured text response in markdown format. (MUST NOT BE EMPTY. Must be >50 characters.)
- "suggested_questions": A clean array of 3-5 strings (no bullet points or numbers, each ending with "?").
Do NOT include any text before or after the JSON block."""

# ── Self-Correction Prompt ──────────────────────────────────────────────────

SELF_CORRECTION_PROMPT = """Your previous output had the following issues:

ERRORS:
{errors}

ORIGINAL CONTEXT (use ONLY this):
---
{context_text}
---

Please fix ALL listed issues and return a valid JSON object with:
- "summary": Non-empty markdown text (minimum 50 characters)
- "suggested_questions": Array of 3-5 question strings

Return ONLY the JSON object, nothing else."""

# ── Document Classification Prompt ─────────────────────────────────────────

CLASSIFY_PROMPT = """Categorize the following document text as EXACTLY one of:
- 'legal_case'  (court judgments, case laws, legal proceedings, petitions, appeals)
- 'general_document'  (reports, emails, contracts, policies, articles, anything else)

Return ONLY the label, nothing else.

TEXT:
{text}"""

# ── Chunk Compression Prompt ────────────────────────────────────────────────

COMPRESS_PROMPT = """Extract the 3 most important sentences from the following text.
Preserve all specific names, dates, numbers, and technical terms exactly as written.
Return ONLY the extracted sentences, nothing else.

TEXT:
{text}"""

# ── General Document Summary Prompt ────────────────────────────────────────

GENERAL_SUMMARY_PROMPT = """TASK: Provide a lucid and professional summary of the document "{file_name}".

{conversation_history}

{json_format}

CONTEXT:
---
{context_text}
---

INSTRUCTIONS:
1. Start with a high-level overview.
2. Use bullet points for "Key Insights" in the summary content.
3. Keep it professional and concise."""

# ── Legal Case Summary Prompt ───────────────────────────────────────────────

LEGAL_SUMMARY_PROMPT = """TASK: Provide a comprehensive, structured legal analysis for the provided case.

SUMMARY STRUCTURE:
1. **Facts**: Background, parties, and events leading to the case.
2. **Issues**: Core legal questions and points of law to be decided.
3. **Arguments**: Contentions from both petitioner/appellant and respondent.
4. **Reasoning**: The court's analysis, interpretation of law, and precedents cited.
5. **Held**: The final decision and Ratio Decidendi (the legal principle established).

EXCERPTS:
---
{context_text}
---

INSTRUCTIONS:
1. Use professional legal terminology.
2. Adhere STRICTLY to the provided excerpts.
3. TONE: Formal, authoritative, and precise.

{json_format}"""

# ── Folder Summary Prompt ───────────────────────────────────────────────────

FOLDER_SYNTHESIS_PROMPT = """TASK: Provide a high-level executive summary of the folder "{folder_name}" 
containing {num_files} files, based on their individual summaries.

FILE SUMMARIES:
---
{file_summaries_text}
---

INSTRUCTIONS:
1. Synthesize the overall purpose and themes across ALL files.
2. Highlight cross-document patterns, relationships, or conflicts.
3. Keep it professional and concise (3-5 paragraphs max).
4. Generate 3-5 specific follow-up questions exploring the folder's contents.

{json_format}"""

# ── Question Answering Prompt ───────────────────────────────────────────────

QUESTION_PROMPT = """TASK: Answer the following question based ONLY on the provided document contexts.

{conversation_history}

CONTEXTS:
---
{context_text}
---

FILES INVOLVED: {file_names}

QUESTION: {question}

INSTRUCTIONS:
1. Be precise and cite the relevant files in your narrative.
2. If the answer isn't in the contexts, say: "I couldn't find information regarding this in the provided documents."
3. If there is conversation history above, use it to resolve any pronouns or references in the question.

{json_format}"""

# ── Multi-Step Research Prompts ─────────────────────────────────────────────

DECOMPOSE_QUERY_PROMPT = """Break down the following complex research question into 2-4 specific
sub-questions that can each be answered by searching a document database.

ORIGINAL QUESTION: {query}

Return ONLY a JSON array of strings (the sub-questions), nothing else.
Example: ["What access events did John Doe trigger?", "What actions were taken after unauthorized access?"]"""

RESEARCH_SYNTHESIS_PROMPT = """TASK: Synthesize a comprehensive research report answering the
original question, based on the findings from multiple document searches.

ORIGINAL QUESTION: {query}

RESEARCH FINDINGS:
---
{research_findings}
---

INSTRUCTIONS:
1. Structure the report clearly with findings from each search step.
2. Cite the source document for every specific finding.
3. Highlight the most important discoveries.
4. Note any gaps where information was not found.

{json_format}"""

# ── Metadata Extraction Prompt ──────────────────────────────────────────────

LEGAL_METADATA_PROMPT = """Extract structured metadata from the following legal text.
Return ONLY a valid JSON object with these exact keys (use null if not found):

{{"court": "...", "year": null, "case_name": "...", "parties": "..."}}

TEXT:
{text}"""

# ── Action Intent Parsing Prompt ────────────────────────────────────────────

ACTION_INTENT_PROMPT = """Identify the action the user wants to perform on Google Drive.
Return ONLY a JSON object with these keys:
- "action": "save_summary" | "create_report" | "unknown"
- "filename": the desired output filename (or null if not specified)
- "parent_folder": the target folder name (or null)

USER REQUEST: {query}"""
