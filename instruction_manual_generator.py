from openai import OpenAI
import json
import os
from typing import Optional, List, Dict, Literal
from json.decoder import JSONDecodeError
import logging

class InstructionManualGenerator:
    def __init__(
        self,
        openai_api_key: str,
        task_goal: str,
        results: List[Dict],
        logger: logging.Logger,
        instruction_format: Literal["text_steps", "json_blocks", "markdown_sections"] = "text_steps", #HW3
        openai_org_id: Optional[str] = None,
        system_role: str = "You are a professional technical document assistant.", #HW3
        max_prompt_tokens: int = 2800, #HW3
        step_tracker: bool = False,       # ★ 新增：是否在每步加上 Step X/Y HW3
        hint_markers: bool = False,       # ★ 新增：是否加入動作提示標記    HW3
    ):
        """
        Initialize the instruction manual generator for WebVoyager tasks.

        Args:
            openai_api_key (str): OpenAI API key.
            task_goal (str): The task goal string (e.g., identifying the professor of a course).
            results (List[Dict]): A list of dictionaries containing retrieved results.
            logger: Logging object
            instruction_format (Literal["text_steps", "json_blocks"]): The desired output format for the manual.
                - "text_steps": Generates a human-readable step-by-step manual.
                - "json_blocks": Outputs a structured JSON manual with descriptions and sources.
            openai_org_id (Optional[str]): OpenAI organization ID.
        """
        self.openai_client = OpenAI(
            api_key=openai_api_key,
            organization=openai_org_id
        )
        self.task_goal = task_goal
        self.results = results
        self.instruction_format = instruction_format
        self.logger = logger

        self.system_role = system_role #HW3
        self.max_prompt_tokens = max_prompt_tokens #HW3
        
        self.step_tracker = step_tracker #HW3
        self.hint_markers = hint_markers #HW3

    #HW3
    def _trim_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """
        粗估 token 數（1 中文字≈1 token；1 英文單字≈1 token）  
        如果超過 max_prompt_tokens 就逐一砍掉最末 chunk。
        """
        total_len = sum(len(c["content"]) for c in chunks)
        while total_len > self.max_prompt_tokens and chunks:
            removed = chunks.pop()          # 從最後面砍最不相關者
            total_len -= len(removed["content"])
        return chunks
    #HW3
    def _generate_prompt(self):
        """
        Build a task-oriented prompt that 包含：
        1) 系統角色與約束
        2) In-context 範例（多產品搜尋＋比較＋查看評論）
        3) 相關性篩選準則
        4) 輸出格式
        5) (經裁切) 檢索段落
        6) 實際任務指令 + self.task_goal
        """
        # 1) 裁切 chunks 避免過長
        relevant_chunks = self._trim_chunks(self.results.copy())

        # 2) 系統角色與約束
        # sys_block = (
        #     f"{self.system_role}\n"
        #     "請遵守以下條件：\n"
        #     "• 回答必須使用繁體中文\n"
        #     "• 步驟以 1. 2. 3. 編號\n"
        #     "• 每步驟動詞開頭、可操作\n\n"
        # )

        # ★ 系統提示：角色 + 通用約束 + 互動設計選項
        sys_block = f"{self.system_role}\n"
        sys_block += "請遵守：\n"
        sys_block += "• 回答必須使用繁體中文\n"
        sys_block += "• 步驟以數字編號，動詞開頭\n"
        if self.step_tracker:
            sys_block += "• 每步前標註 'Step <編號>/<總步驟數>'\n"
        if self.hint_markers:
            sys_block += "• 如有需要，在步驟前加入提示標記（例如 '現在請依日期篩選：'）\n"
        sys_block += "\n"

        # 3) In-context 範例：多產品搜尋＋比較＋查看評論
        example_block = (
            "【範例】\n"
            "Task Goal: 在 Amazon.jp 搜尋並比較『アミノバイタル タブレット』和『DHC マルチビタミン』\n"
            "Steps:\n"
            "1. 開啟瀏覽器並前往 https://www.amazon.co.jp/ \n"
            "2. 在搜尋框輸入「アミノバイタル タブレット」並按 Enter\n"
            "3. 在左側篩選面板設定價格區間為 1,000-3,000 日圓\n"
            "4. 在搜尋結果頁瀏覽五個商品，快速比較它們的名稱、價格與星級評分摘要\n"
            "5. 點擊評價星數 ≧ 4 星的第一個商品，進入詳細頁\n"
            "6. 點擊「カスタマーレビュー」標籤，切換到評論區\n"
            "7. 閱讀前五則高評分評論，確認產品真實用戶回饋\n\n"
        )

        # 4) 相關性篩選準則
        relevance_block = (
            "【相關性篩選準則】\n"
            "- 必須與購物流程直接相關（搜尋、比較、篩選、點擊、評論）\n"
            "- 包含明確的操作方法或介面元素\n"
            "- 如為多種方案，呈現為「方法1」「方法2」\n\n"
        )

        # 5) 輸出格式
        format_block = (
            "【輸出格式】\n"
            "請將最終結果列為：\n"
            "Task Goal: {self.task_goal}\n"
            "Steps:\n"
            "1. …\n"
            "2. …\n"
            "...\n\n"
        )

        # 6) 檢索到的段落（精簡後）
        doc_block = "【檢索到的相關段落】\n"
        for idx, c in enumerate(relevant_chunks, 1):
            doc_block += (
                f"[{idx}] Section: {c['section']} (p.{c.get('page','?')})\n"
                f"{c['content']}\n\n"
            )

        
        # user_block = (
        #     "【實際任務】\n"
        #     f"Task Goal: {self.task_goal}\n\n"
        #     "請閱讀上方段落，根據【相關性篩選準則】過濾資訊，並依【輸出格式】"
        #     "列出可直接執行的操作步驟：\n"
        #     "- 僅引用段落中有的資訊，勿杜撰\n"
        #     "- 如有需要，可在步驟後標註 (引自段落 #[idx])\n"
        # )

        # 7) 最後實際任務指令
        user_block = (
            "【實際任務】\n"
            f"Task Goal: {self.task_goal}\n\n"
            "請閱讀上方段落，過濾真正可執行的內容，並產生操作步驟：\n"
        )
        if self.step_tracker:
            user_block += "- 每步包含 'Step <編號>/<總步驟數>' 標記\n"
        if self.hint_markers:
            user_block += "- 如需提示，請在步驟前加入動作提示標記\n"
        user_block += (
            "- 僅引用段落中有的資訊，勿杜撰\n"
            "- 如需引用，標註 (引自段落 #[idx])\n"
        )

        # 8) 拼裝並回傳
        prompt = (
            sys_block
            + example_block
            + relevance_block
            + format_block
            + doc_block
            + user_block
        )
        return prompt

    #HW3
#     def _generate_prompt(self):
#         """
#         Generates the prompt for OpenAI's GPT model based on task goal and results.
#         :return: The formatted prompt string.
#         """
#         prompt = f"""
# You are a professional technical document assistant for WebVoyager, a web browsing agent. Your task is to filter relevant information from the provided retrieval results based on the given task goal and compile it into a structured instruction manual with actionable, numbered steps to guide the agent in completing the task.

# ### Task Goal:
# {self.task_goal}

# ### Retrieval Results Example:
# Each result contains:
# - section: (The title information)
# - content: (The information retrieved)
# - source: (The source of the information)

# ### Relevance Criteria:
# - The goal is to compile an **instruction manual** that provides actionable steps to achieve the task.
# - A result is **relevant** if it:
#   - Contains keywords or terminology directly related to any possible approach for completing the task goal
#   - Includes step-by-step instructions, procedures, or operations that could contribute to task completion
#   - Describes key functions, tools, or settings that might be useful for the task
#   - Contains configuration details, system behaviors, or technical information that could aid in achieving the goal
#   - Provides partial but useful information, even if it only addresses one aspect of the task
#   - Mentions alternative methods or approaches that could accomplish the same goal
# - A result is **not relevant** if it:
#   - Contains no keywords or terminology related to any approach for completing the task
#   - Provides only general theoretical concepts without practical application
#   - Is completely unrelated to the task goal or any of its components

# ### Filtering Process:
# 1. **Identify Relevant Information**  
#    - Consider whether the retrieved content helps in accomplishing the task through ANY possible approach
#    - Even if the information describes just one possible method or only a portion of a method, include it
#    - If a section contains even one relevant keyword or concept related to task completion, consider it relevant

# 2. **Structured Output**  
#    - Organize the relevant information into a step-by-step instruction manual
#    - Each step must be actionable, clearly described, and numbered sequentially
#    - Use action-oriented language (e.g., "Click the search button," "Type 'query' into the textbox") to ensure clarity
#    - If multiple methods are available, present them as alternative approaches with clear labels (e.g., "Method 1: Step 1")
#    - For irrelevant results, provide a clear explanation of why they do not contribute to the task goal

# ### Output Format:
# Return a string containing the structured manual with numbered steps. Each step should be concise and actionable. Format as follows:
# ```
# Task Goal: {self.task_goal}
# Steps:
# 1. [Actionable step description]
# 2. [Actionable step description]
# ...

# source: [The source of the information]
# ```

# ### Example:
# For a task like "Search for the latest news on climate change":
# ```
# Task Goal: Search for the latest news on climate change
# Steps:
# 1. Open your web browser and navigate to www.google.com.
# 2. Type 'climate change latest news' into the search bar and press Enter.
# 3. Click on a news article from a reputable source like BBC or Reuters.
# ```

# ### Retrieval Results
# {json.dumps(self.results, ensure_ascii=False, indent=2)}

# Please reason step by step and ensure the manual is structured with clear, actionable steps tailored for a web browsing agent.
# """

#         if self.instruction_format == "json_blocks":
#             prompt = f"""
# You are a professional technical document assistant. Your task is to filter the relevant information from the provided retrieval results based on the given task goal and compile it into an instruction manual.

# ### Task Goal:
# {self.task_goal}

# ### Retrieval Results Example:
# Each result contains:
# - section: (The title information)
# - content: (The information retrieved)
# - source: (The source of the information)

# ### Relevance Criteria:
# - The goal is to compile an **instruction manual** that provides actionable steps to achieve the task.
# - A result is **relevant** if it:
#   - Contains keywords or terminology directly related to any possible approach for completing the task goal
#   - Includes step-by-step instructions, procedures, or operations that could contribute to task completion
#   - Describes key functions, tools, or settings that might be useful for the task
#   - Contains configuration details, system behaviors, or technical information that could aid in achieving the goal
#   - Provides partial but useful information, even if it only addresses one aspect of the task
#   - Mentions alternative methods or approaches that could accomplish the same goal
# - A result is **not relevant** if it:
#   - Contains no keywords or terminology related to any approach for completing the task
#   - Provides only general theoretical concepts without practical application
#   - Is completely unrelated to the task goal or any of its components

# ### Filtering Process:
# 1. **Identify Relevant Information**
#    - Consider whether the retrieved content helps in accomplishing the task through ANY possible approach
#    - Even if the information describes just one possible method or only a portion of a method, include it
#    - If a section contains even one relevant keyword or concept related to task completion, consider it relevant

# 2. **Structured Output**
#    - Format relevant results in JSON, including the title, description, and source
#    - For irrelevant results, provide a clear explanation of why they do not contribute to the task goal


# ### Retrieval Results
# {json.dumps(self.results, ensure_ascii=False, indent=2)}

# ### Output Format:
# Please output the results in the following JSON format:
# ```json
# {{
#     "manual": [
#         {{
#             "title": "Relevant Title",
#             "description": "Operation steps filtered and compiled based on the task goal from the retrieved content",
#             "source": "Source of the information"
#         }}
#     ],
#     "irrelevant_explanations": [
#         {{
#             "section": "Title of the irrelevant section",
#             "reason": "Explanation of why this result is not relevant"
#         }}
#     ]
# }}
# ```
# """
#         return prompt

    def _call_openai(self, prompt: str) -> str:
        """
        Call OpenAI's GPT API with the provided prompt and return the response.

        Args:
            prompt (str): The generated prompt string.

        Returns:
            str: The response from OpenAI's API.
        """
        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": self.system_role},
                      {"role": "user", "content": prompt}],
            temperature=0.3
        )

        return response.choices[0].message.content

    def generate_instruction_manual(self) -> str:
        """
        Generates a structured instruction manual by filtering relevant information from the retrieval results
        based on the defined task goal.

        This method works by:
        1. Generating a prompt using the task goal and retrieved content.
        2. Sending the prompt to the OpenAI API via `_call_openai()` to obtain a response.
        3. Handling the response based on the selected `instruction_format` (default: "text_steps"):
           - If `instruction_format` is "text_steps" (default), the method returns a free-form,
             step-by-step instruction manual directly from the model response.
           - If `instruction_format` is "json_blocks", the method parses the JSON response and converts each entry
             (including title, description, and source) into a readable manual string.

        Returns:
            str: A formatted instruction manual string, either as:
                - A step-by-step plain-text guide (if `instruction_format` is "text_steps"), or
                - A structured set of entries parsed from JSON, including title, description, and source (if `instruction_format` is "json_blocks").
        """
        prompt = self._generate_prompt()
        response_text = self._call_openai(prompt)

        if self.instruction_format == "json_blocks":
            try:
                response_text = response_text.replace("```json", "").replace("```", "")
                response = json.loads(response_text)
                manual_obj = response["manual"]

                manual_str = "\n\n".join(
                    f"title: {entry['title']}\ndescription: {entry['description']}\nsource: {entry['source']}"
                    for entry in manual_obj
                )
                return manual_str

            except JSONDecodeError as e:
                self.logger.warning(f"[JSONDecodeError] Failed to parse response: {e}")
            except (KeyError, TypeError) as e:
                self.logger.warning(f"[FormatError] Missing expected fields in JSON response: {e}")

            return ""
        elif self.instruction_format == "markdown_sections": #HW3
            # 把模型回的每行文字裡以 "Step" 開頭的行，前面加上 "### "
            lines = response_text.splitlines()
            sections = [f"### {line}" for line in lines if line.lower().startswith("step")]
            return "\n\n".join(sections)
        else:
            logging.info(f"Response from OpenAI: {response_text}")
            return response_text


# Example Usage
if __name__ == "__main__":

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

    # Get API key from environment variable
    api_key = os.getenv("OPENAI_API_KEY")
    org_id = os.getenv("OPENAI_ORG_ID")

    task_goal = "查詢資訊工程學系碩士班的課程中，AI代理系統之設計與開發這門課的授課教授是誰?"
    results = [
        {"section": "Course Information",
         "content": "The course 'AI Agent System Design and Development' is taught by Professor Zhang.",
         "source": "University Course Announcement"},
        {"section": "University News", "content": "The university is promoting intelligent course development...",
         "source": "University News Website"},
        {"section": "Student Forum", "content": "Does anyone know who teaches the AI agent system course?",
         "source": "Student Forum"}
    ]

    # Instantiate the class and generate the manual
    manual_generator = InstructionManualGenerator(
        openai_api_key=api_key,
        openai_org_id=org_id,
        task_goal=task_goal,
        results=results,
        logger=logger
    )
    manual = manual_generator.generate_instruction_manual()

    # Print the resulting manual
    print(manual)
