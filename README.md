<div align="center">
<h1> WebPriceCompare 
<img src="./assets/icon.png" width="45px">
<br> Multi-Site Price Comparison Web Agent </h1>
</div>

<div align="center">

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10.13-green.svg)
![Selenium](https://img.shields.io/badge/Selenium-4.15.2-red)

</div>

<div align="center">
<img src="./assets/overall_process_crop.png" width="90%">
</div>

## (New Update) PDF RAG Processing Pipeline

This section is responsible for breaking the original PDF manual into modular pieces and structuring them into a vector database for efficient RAG retrieval. The workflow includes:

1. **Document Parsing and Text Extraction**
   - **pdf_to_text**: Use `pdfplumber` to extract searchable text; if a page has no text (e.g., it’s a scanned image), invoke OCR with `pytesseract` to recognize text on the image (supports Traditional Chinese, Japanese, etc.).
   - **pdf_to_markdown** (optional): If you need to annotate screenshots or tables further, use `pymupdf` to generate Markdown and preserve image paths for downstream enrichment.

2. **TOC Parsing and Section Splitting**
   - If the PDF includes a table of contents, extract the page–section mapping and split the file by section.
   - Otherwise, split by “every N pages” or when encountering large headings to ensure semantic units remain coherent.

3. **Chunking Strategy**
   - **TokenTextSplitter**: Defaults to `chunk_size=500` and `chunk_overlap=100` characters, with `splitter_type="token"`.
   - **RecursiveCharacterTextSplitter**: For more natural breakpoints, switch to `splitter_type="recursive"`, prioritizing punctuation and line breaks.
   - Users can fine-tune `chunk_size` and `chunk_overlap` to adapt to different manuals’ text density.

4. **Metadata Organization**
   - Each chunk is tagged with:
     - `source`: original file path  
     - `section`: section title  
     - `page`: starting page number  
     - `timestamp`: file’s last modification time (ISO format)  
   - These fields enable filtering and re-ranking during retrieval.

5. **Vectorization and Indexing**
   - Use `EmbeddingFactory` (default: `OpenAIEmbeddings`) to convert each text segment into a vector.
   - Store vectors and metadata in a Chroma vector database, with persistence (`persist_directory`) and multi-task sharing support.

6. **Quick Start Example**
   ```bash
   from pdf_rag import PDFEnhancementPipeline

   pipeline = PDFEnhancementPipeline(
       openai_api_key="YOUR_API_KEY",
       persist_directory="./chroma_db"
   )
   pipeline.process_pdf(
       pdf_path="data/manual.pdf",
       output_dir="manual_output",
       add_image_descriptions=False,
       index_for_rag=True,
       rag_mode="overwrite",
       use_ocr=True,
       chunk_size=600,
       chunk_overlap=120,
   )  

## (New Update) Automated Instruction Manual Generation

Automatically generate a structured, actionable manual by combining RAG-retrieved passages with prompt engineering.

1. **Retrieval Preparation**
   - **Inputs**:  
     - `task_goal` (the user’s objective)  
     - `current_intent` (agent’s intent)  
     - RAG search parameters (`k`, `summarize`)  
   - RAGEngine re-ranks results based on intent and query, returning the top `k` chunks. Long chunks can be summarized to the “first 200 + last 200 characters.”

2. **Prompt Assembly**
   - **System Prompt**  
     - Define role (e.g., “You are the instruction-manual author for WebVoyager.”)  
     - Enforce strict formatting: numbered steps, verbs at the start.  
     - Enable `step_tracker` to label “Step X/Y”; enable `hint_markers` to insert hint labels.
     - Example :
       ```
        Task Goal: 在 Amazon.jp 搜尋並比較『アミノバイタル タブレット』和『DHC マルチビタミン』
        Steps:
        1. 開啟瀏覽器並前往 https://www.amazon.co.jp/
        2. 在搜尋框輸入「アミノバイタル タブレット」並按放大鏡圖示執行搜尋 (引自段落 #[1])。
        3. 在左側篩選面板設定價格區間，拖動價格滑桿並點擊「検索」更新結果 (引自段落 #[1])。
        4. 在搜尋結果頁瀏覽五個商品，快速比較它們的名稱、價格與星級評分摘要。
        5. 點擊評價星數 ≧ 4 星的第一個商品，進入詳細頁。
        6. 點擊「カスタマーレビュー」標籤，切換到評論區。
        7. 閱讀前五則高評分評論，確認產品真實用戶回饋。
       ```
   - **In-Context Example**: Provide a brief formatted example to align the model’s output style.  
   - **Document Block**: List each chunk in order, label as `[Index] Section: … (p.X)`, and include its summarized `content`.  
   - **User Instruction**  
     - Restate the `task_goal`.  
     - Remind: “Only cite the above passages; do not fabricate.”  
     - When citing a chunk, annotate `(from chunk #idx)`.

3. **Calling the LLM**
   - Use `gpt-4o-mini` (or another specified model) for Chat Completion.  
   - Set `temperature` around `0.3` to balance creativity and stability.  
   - Recommend `max_tokens` below `500` to avoid hitting the token limit.

4. **Post-Processing**
   - Split the LLM’s reply by line; treat each line as a discrete step.  
   - **Options**:  
     - Take the first N lines as a “concise manual,” or  
     - Keep all steps and include section headings/indexes.  
   - For JSON output (`instruction_format="json_blocks"`), convert lines into a list of JSON blocks for programmatic use.

5. **Full Usage Example**
   ```python
   from instruction_manual_generator import InstructionManualGenerator
   import logging

   # Assume `chunks` is the list returned from pipeline.search()
   chunks = [...]

   # Generate the manual
   manual_gen = InstructionManualGenerator(
       openai_api_key="YOUR_API_KEY",
       task_goal="Search and compare “Amino Vital Tablets” and “DHC Multivitamins” on Amazon.jp",
       results=chunks,
       logger=logging.getLogger(),
       instruction_format="text_steps",
       step_tracker=True,
       hint_markers=True
   )
   manual = manual_gen.generate_instruction_manual()
   print(manual)

## Introduction

This repository contains the code for **WebPriceCompare**, an AI-powered web agent designed to compare product prices across multiple e-commerce websites. This project is based on **WebVoyager** ([original repo](https://arxiv.org/abs/2401.13919)) and has been modified to enable automated price comparisons.

### Key Features
- **Multi-Site Price Comparison**: The agent browses multiple e-commerce websites and extracts product prices for comparison.
- **Automated Web Interaction**: Uses Selenium to navigate, search for products, and extract price information.
- **AI-Powered Decision Making**: Uses GPT-4o-mini to determine the lowest price and generate a final decision.
- **Support for Dynamic Pages**: Handles pages with AJAX loading, pop-ups, and accessibility tree-based navigation.

## Setup Environment

### Prerequisites
1. Ensure that **Google Chrome** is installed. (The latest Selenium version does not require ChromeDriver installation.)
2. If running on a **Linux server**, install Chromium (e.g., for CentOS: `yum install chromium-browser`).

### Installation
Create a Conda environment and install dependencies:
```bash
conda create -n webpricecompare python=3.10
conda activate webpricecompare
pip install -r requirements.txt
```

## Data

### Task Format
Each task specifies a product to search for and a list of e-commerce websites to check. The dataset format follows:
```json
{
    "id": 1,
    "product": "a portable Bluetooth speaker with a water-resistant design",
    "websites": [
        "https://www.amazon.com",
        "https://www.bestbuy.com",
        "https://www.walmart.com"
    ],
    "ques": "Find the product on each website. Only answer the best one."
}
```
The dataset is stored in `data/tasks_test.jsonl`.

## Running

### Running WebPriceCompare
1. Add product queries in `data/tasks_test.jsonl`.
2. Set your OpenAI API key in `run.sh`.

#### **Method 1: Using Bash Script (`run.sh`)**
Run the agent:
```bash
bash run.sh
```

#### `run.sh` Example
```bash
#!/bin/bash
nohup python -u run.py \
    --test_file ./data/tasks_test.jsonl \
    --api_key YOUR_OPENAI_API_KEY \
    --headless \
    --max_iter 15 \
    --max_attached_imgs 3 \
    --temperature 1 \
    --fix_box_color \
    --seed 42 > test_tasks.log &
```

#### **Method 2: Windows Direct Execution**
For **Windows users**, you can run the agent directly:
```powershell
"C:\Users\user\AppData\Local\Programs\Python\Python310\python.exe" run.py --temperature 0.0 --test_file data/tasks_test.jsonl --api_key "YOUR-OPENAI-API-KEY" --api_model gpt-4o-mini
```

### Output
- Screenshots and interaction logs are stored in the `results/` directory.
- The final decision on the **lowest price** is printed and logged.

## Parameters

- `--test_file`: JSON file with product queries.
- `--max_iter`: Maximum number of interactions per task.
- `--api_key`: OpenAI API key for processing.
- `--output_dir`: Directory for storing results.
- `--download_dir`: Directory for downloading files (if needed).
- `--headless`: Run without opening a visible browser.
- `--max_attached_imgs`: Number of screenshots to retain for context.
- `--text_only`: Enable text-based navigation (without images).
- `--temperature`: Control randomness of AI responses.


## Results and Evaluation

After execution, the system selects the lowest-priced product and generates a final report. Example output:

```
Product: Bluetooth speaker (黑色)
Website: Amazon
Price: $21.99

Product: JBL Go4 Bluetooth Wireless Speaker
Website: Target
Price: $39.99
```


> **Reflection Agent’s Analysis**  
> - Compared **Bluetooth speaker (黑色)** (Amazon, $21.99) vs. **JBL Go4 Bluetooth Wireless Speaker** (Target, $39.99)  
> - Noted that the JBL brand offers stronger reputation, higher quality and better user trust, despite higher cost  
> - **Conclusion:** Chose **JBL Go4 Bluetooth Wireless Speaker** for its reliable performance and brand value

```text
Product: JBL Go4 Bluetooth Wireless Speaker
Website: Target
Price: $39.99
```

> **Debater Agent’s Feedback**  
> - **Accept: Yes**  
> - **Explanation:** The reflection clearly compared brand reputation, pricing, and long‑term value, and the reasoning for selecting the JBL product is sound and helpful to potential buyers.

---

## Agent Architecture
- **Executor Agent**: Drives the browsing loop, calls GPT‑4o-mini to generate “Thought”/“Action”, parses them, and executes via Selenium.  
- **Error Grounding Agent**: After each action (>1), analyzes screenshot vs. intended Thought, returns `Errors: Yes/No` + explanation, which is injected into the next prompt.  
- **Reflection Agent**: After collecting multiple candidate products, compares on brand reputation, discount, shipping, and outputs a detailed chain‑of‑thought final recommendation.  
- **Debater Agent**: Reviews the Reflection Agent’s decision (Accept: Yes/No). If rejected, triggers a re‑reflection cycle.  

## Error Analysis & Strategy Adjustment
- **Structured Error History**: All failures (`error_type`, `iteration`, `message`) are logged into a global `error_history`.  
- **Automated EGA Calls**: Each iteration wraps a call to the Error Grounding Agent, feeding back errors into prompts for self‑correction.  
- **Format & Exception Handling**:  
  - Enhanced `extract_information` supports multiple scroll syntaxes and auto‑fills missing `Thought:`.  
  - Main loop catches stale element references, invalid indices, and format errors—logging and retrying accordingly.

## Prompt Enhancements
- **System Prompts** now enforce:  
  - **“Scroll at least twice and collect ≥2 candidates before final decision.”**  
  - **“Use only `Answer; …` for the final answer.”**  
  - **Reference to `error_history`** so the agent can leverage past failures.  
- **`SYSTEM_PREVIOUS_STEP`** upgraded with 6 concrete guidelines (avoid repeats, always scroll, heed EGA feedback, etc.).  
- Separate constants for Reflection, Debater, Orchestration, and EGA prompts, clarifying each agent’s contract.

## Utility Functions Enhancements
- **Scroll Parsing**: `extract_information` now handles both `Scroll [n]; down` and `Scroll down; [n]`.  
- **`print_message` Simplification**: Only skips `system` messages and extracts the final “Answer” into structured product info.  
- **Context Clipping**: Improved `clip_message_and_obs(_text_only)` for screenshots, PDFs, and text‑only modes to keep prompts concise.

## CLI & Run Enhancements
- **New Flags**:  
  - `--trajectory`: record full iteration history in prompts.  
  - `--error_max_reflection_iter`: max retries for re‑reflection cycles.  
- **Message Formatting**:  
  - `format_msg` / `format_msg_text_only` accept a `prev_step_action` block to inject review history + EGA feedback.  
  - `sanitize_messages` hides system internals when calling sub‑agents.  
- **Logging**: `setup_logger` now captures all agent interactions (Executor, EGA, Reflection, Debater) in `agent.log` for full traceability.

---

## Citation

If you use or modify this project, please also consider citing the original WebVoyager paper:
```
@article{he2024webvoyager,
  title={WebVoyager: Building an End-to-End Web Agent with Large Multimodal Models},
  author={He, Hongliang and Yao, Wenlin and Ma, Kaixin and Yu, Wenhao and Dai, Yong and Zhang, Hongming and Lan, Zhenzhong and Yu, Dong},
  journal={arXiv preprint arXiv:2401.13919},
  year={2024}
}
```

## Disclaimer

This project is **not** an official product and does not guarantee accurate results due to the dynamic nature of web pages, AI decision-making, and API changes. Users should verify extracted data before use.
