class PromptBuilder:
    """Consolidates prompts for legal and general RAG flows."""

    # General Prompts
    SYSTEM_INSTRUCTION = """You are a professional analysis assistant with a lucid and highly readable writing style.
ONLY use information from the PROVIDED CONTEXT. If the answer is not in the context, say so clearly.
TONE: Professional, concise, and structured. Use clear headers and bullet points."""

    GENERAL_SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTION

    # Specialized System Instructions
    LEGAL_SYSTEM_INSTRUCTION = """You are a senior legal analyst preparing concise, accurate notes for Indian judiciary exams.
    Your task is to analyze judicial excerpts and produce a structured, professional legal summary.

    STRICT RULES:
    1. ONLY use information from the provided excerpts.
    2. If a section (e.g. "Arguments") is missing from the excerpts, say: "Not explicitly mentioned in the provided text."
    3. TONE: Formal, authoritative, and precise.
    4. LANGUAGE: Use professional legal terminology (e.g. "Ratio Decidendi", "Inter alia").
    5. ACCURACY: Do not hallucinate or extrapolate beyond the text.
    """

    JSON_FORMAT_INSTRUCTION = """
IMPORTANT: Return your output strictly as a JSON object with these keys:
- "summary": The structured text response in markdown format. (MUST NOT BE EMPTY)
- "suggested_questions": A clean array of 3-5 strings (no bullet points or numbers).
Do NOT include any text before or after the JSON block. The "summary" field must contain the full analysis."""


    FOLDER_SUMMARY_PROMPT = """TASK: Provide a high-level summary of the folder "{folder_name}" and suggest follow-up questions based on its contents.

FILE EXCERPTS:
---
{combined_text}
---

INSTRUCTIONS:
1. Synthesize the overall purpose of these {num_files} files.
2. Highlight cross-document themes or relationships.
3. Keep it professional and concise.
4. IMPORTANT: You MUST generate 3-5 specific follow-up questions exploring the contents of these documents.

{json_instruction}
"""

    QUESTION_PROMPT = """TASK: Answer the following question based ONLY on the provided document contexts.

CONTEXTS:
---
{chunks_text}
---

FILES INVOLVED: {file_names}

QUESTION: {question}

INSTRUCTIONS:
1. Be precise and cite the relevant files in your narrative.
2. If the answer isn't in the contexts, say: "I couldn't find information regarding this in the provided documents."

{json_instruction}
"""

    # Legal Extraction & Synthesis (All-in-One)
    LEGAL_ALL_IN_ONE_PROMPT = """TASK: Provide a comprehensive, structured legal analysis and follow-up questions for the provided case based ONLY on the excerpts provided.

SUMMARY STRUCTURE:
1. **Facts**: Background, parties, and events leading to the case.
2. **Issues**: Core legal questions and points of law to be decided.
3. **Arguments**: Contentions from both petitioner/appellant and respondent.
4. **Reasoning**: The court's analysis, interpretation of law, and precedents cited.
5. **Held**: The final decision and Ratio Decidendi (the legal principle established).

EXCERPTS:
---
{chunks_text}
---

INSTRUCTIONS:
1. Use professional legal terminology.
2. Adhere STRICTLY to the provided excerpts.
3. TONE: Formal, authoritative, and precise.

{json_instruction}
"""

    SUGGESTED_QUESTIONS_PROMPT = """TASK: Based ON THE SUMMARY ABOVE, generate 3-4 concise follow-up questions that a user might want to ask to explore the case further.
 
FORMAT:
- Return only the questions, one per line.
- Each line MUST start with a bullet point '-' or a number '1.'
- Do not include categories, labels, or extra text.
- Keep each question relevant and exploratory.
 
SUMMARY:
---
{summary_text}
---
### Suggested Questions
"""

    # General Prompts
    GENERAL_SUMMARY_PROMPT = """TASK: Provide a lucid and professional summary of the document "{file_name}".

{json_instruction}

CONTEXT:
---
{chunks_text}
---

INSTRUCTIONS:
1. Start with a high-level overview.
2. Use bullet points for "Key Insights" in the summary content."""

    def build_judicial_question_prompt(self, summary_text: str) -> str:
        return self.SUGGESTED_QUESTIONS_PROMPT.format(summary_text=summary_text)

    def build_general_summary_prompt(self, file_name: str, chunks_text: str) -> str:
        return self.GENERAL_SUMMARY_PROMPT.format(
            file_name=file_name, 
            chunks_text=chunks_text,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )

    def build_folder_summary_prompt(self, folder_name: str, combined_text: str, num_files: int) -> str:
        return self.FOLDER_SUMMARY_PROMPT.format(
            folder_name=folder_name, 
            combined_text=combined_text, 
            num_files=num_files,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )

    def build_question_prompt(self, question: str, chunks_text: str, file_names: str) -> str:
        return self.QUESTION_PROMPT.format(
            question=question, 
            chunks_text=chunks_text, 
            file_names=file_names,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )
