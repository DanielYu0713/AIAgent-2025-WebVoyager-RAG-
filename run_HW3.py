import platform
import argparse
import time
import json
import re
import os
import shutil
import logging
import sys
import pyautogui  # 改動

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# HW2: 新增或修改的 import
from prompts_HW3 import (
    SYSTEM_PROMPT,                # HW2: 基本系統提示
    SYSTEM_PROMPT_TEXT_ONLY,      # HW2: Text-only 模式提示
    SYSTEM_REFLECTION_PROMPT,     # HW2: Reflection Agent 提示
    SYSTEM_ORCHESTRATION_PROMPT,  # HW2: Orchestration Agent 提示
    ERROR_GROUNDING_AGENT_PROMPT, # HW2: EGA 提示
    SYSTEM_PREVIOUS_STEP,         # HW2: 更新後的前一步驟提示
    DEBATER_AGENT_PROMPT          # HW2: 新增 Debater Agent 提示
)

from openai import OpenAI
from utils_HW3 import (  # HW2: 這裡改成 utils_HW2
    get_web_element_rect,
    encode_image,
    extract_information,
    print_message,
    get_webarena_accessibility_tree,
    get_pdf_retrieval_ans_from_assistant,
    clip_message_and_obs,
    clip_message_and_obs_text_only,
    compare_images
)

from pdf_rag import PDFEnhancementPipeline              # 建立 & 查詢向量庫 HW3
from instruction_manual_generator import InstructionManualGenerator  # 產生操作手冊 HW3

#HW3 Debug用 -----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)
#HW3 Debug用 -----------

def setup_logger(folder_path):
    log_file_path = os.path.join(folder_path, 'agent.log')
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)

def driver_config(args):
    options = webdriver.ChromeOptions()
    if args.save_accessibility_tree:
        args.force_device_scale = True
    if args.force_device_scale:
        options.add_argument("--force-device-scale-factor=1")
    if args.headless:
        options.add_argument("--headless")
        options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
    options.add_experimental_option("prefs", {
        "download.default_directory": args.download_dir,
        "plugins.always_open_pdf_externally": True
    })
    options.add_argument("disable-blink-features=AutomationControlled")
    return options

# HW2: 修改後的 format_msg，增加 prev_step_action 參數
def format_msg(it, init_msg, pdf_obs, warn_obs, web_img_b64, web_text, prev_step_action=""):
    """
    將當前步驟（iteration）組成 user message 格式 (非 text-only)
    """
    if it == 1:
        init_msg_full = prev_step_action + "\n" + init_msg + "\nI've provided the tag name of each element and its text (if exists). Please focus on the screenshot and textual details.\n" + web_text
        msg_format = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': init_msg_full},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{web_img_b64}"}}
            ]
        }
        return msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': [
                    {
                        'type': 'text',
                        'text': (
                            prev_step_action
                            + "\nObservation: "
                            + warn_obs
                            + " please analyze the attached screenshot and give the Thought and Action.\n"
                            + web_text
                        )
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{web_img_b64}"}}
                ]
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': [
                    {
                        'type': 'text',
                        'text': (
                            prev_step_action
                            + "\nObservation: "
                            + pdf_obs
                            + " please analyze the Assistant’s response and decide whether to continue.\n"
                            + web_text
                        )
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{web_img_b64}"}}
                ]
            }
        return curr_msg

# HW2: 修改後的 format_msg_text_only，同樣加入 prev_step_action
def format_msg_text_only(it, init_msg, pdf_obs, warn_obs, ac_tree, prev_step_action=""):
    """
    將當前步驟（iteration）組成 user message 格式 (text-only 模式)
    """
    if it == 1:
        return {
            'role': 'user',
            'content': prev_step_action + "\n" + init_msg + '\n' + ac_tree
        }
    else:
        if not pdf_obs:
            return {
                'role': 'user',
                'content': (
                    prev_step_action
                    + "\nObservation:"
                    + warn_obs
                    + " please analyze the accessibility tree and give the Thought and Action.\n"
                    + ac_tree
                )
            }
        else:
            return {
                'role': 'user',
                'content': (
                    prev_step_action
                    + "\nObservation: "
                    + pdf_obs
                    + " please analyze the Assistant’s response and decide whether to continue.\n"
                    + ac_tree
                )
            }

def call_gpt4v_api(args, openai_client, messages):
    retry_times = 0
    while True:
        try:
            if not args.text_only:
                logging.info("[GPT-4o-mini] Calling gpt4v API...")
                openai_response = openai_client.chat.completions.create(
                    model=args.api_model,
                    messages=messages,
                    max_tokens=500,
                    temperature=args.temperature,  # 建議可調低到0.2~0.3
                    seed=args.seed
                )
            else:
                logging.info("[GPT-4o-mini] Calling gpt4 API...")
                openai_response = openai_client.chat.completions.create(
                    model=args.api_model,
                    messages=messages,
                    max_tokens=500,
                    temperature=args.temperature,  # 同上，建議可調低
                    seed=args.seed,
                    timeout=30
                )
            time.sleep(1)
            prompt_tokens = openai_response.usage.prompt_tokens
            completion_tokens = openai_response.usage.completion_tokens
            logging.info(f"[GPT-4o-mini] Prompt Tokens: {prompt_tokens}; Completion Tokens: {completion_tokens}")
            return prompt_tokens, completion_tokens, False, openai_response
        except Exception as e:
            logging.info(f"[GPT-4o-mini] Error occurred, retrying. Error type: {type(e).__name__}")
            if type(e).__name__ == 'RateLimitError':
                time.sleep(10)
            elif type(e).__name__ == 'APIError':
                time.sleep(15)
            elif type(e).__name__ == 'InvalidRequestError':
                return None, None, True, None
            else:
                return None, None, True, None
            retry_times += 1
            if retry_times == 10:
                logging.info('[GPT-4o-mini] Retrying too many times')
                return None, None, True, None

def wait_for_page_load(driver, timeout=20):
    """
    等待網頁 load 完成 (document.readyState)
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if driver.execute_script("return document.readyState;") == "complete":
            return True
        time.sleep(1)
    return False

def exec_action_refresh(driver_task):
    driver_task.refresh()
    if wait_for_page_load(driver_task, timeout=20):
        time.sleep(3)
    else:
        time.sleep(3)

def exec_action_zoom(info, driver_task):
    zoom_value = info['content'].strip()
    try:
        zoom_ratio = float(zoom_value)
        driver_task.execute_script(f"document.body.style.zoom = '{zoom_ratio}';")
    except ValueError:
        current_zoom = driver_task.execute_script("return document.body.style.zoom;")
        try:
            current_zoom = float(current_zoom) if current_zoom else 1.0
        except:
            current_zoom = 1.0
        try:
            pixel_adjust = float(zoom_value)
        except:
            pixel_adjust = 0
        new_zoom = current_zoom + (pixel_adjust / 1000.0)
        driver_task.execute_script(f"document.body.style.zoom = '{new_zoom}';")
    time.sleep(3)

def exec_action_click(info, web_ele, driver_task):
    driver_task.execute_script("arguments[0].setAttribute('target', '_self')", web_ele)
    web_ele.click()
    time.sleep(3)

def exec_action_type(info, web_ele, driver_task):
    warn_obs = ""
    type_content = info['content']
    ele_tag_name = web_ele.tag_name.lower()
    ele_type = web_ele.get_attribute("type")
    if (ele_tag_name not in ['input', 'textarea']) or (
        ele_tag_name == 'input' and ele_type not in ['text', 'search', 'password', 'email', 'tel']
    ):
        warn_obs = f"note: The element may not be a textbox (<{web_ele.tag_name}> type: {ele_type})."
    try:
        web_ele.clear()
        if platform.system() == 'Darwin':
            web_ele.send_keys(Keys.COMMAND + "a")
        else:
            web_ele.send_keys(Keys.CONTROL + "a")
        web_ele.send_keys(" ")
        web_ele.send_keys(Keys.BACKSPACE)
    except:
        pass
    actions = ActionChains(driver_task)
    actions.click(web_ele).perform()
    actions.pause(1)
    try:
        driver_task.execute_script(
            """window.onkeydown = function(e) {
                if(e.keyCode == 32 && e.target.type != 'text'
                   && e.target.type != 'textarea'
                   && e.target.type != 'search') {
                    e.preventDefault();
                }
            };"""
        )
    except:
        pass
    actions.send_keys(type_content)
    actions.pause(2)
    actions.send_keys(Keys.ENTER)
    actions.perform()
    time.sleep(10)
    return warn_obs

def exec_action_scroll(info, web_eles, driver_task, args, obs_info):
    scroll_ele_number = info['number']
    scroll_content = info['content']
    if scroll_ele_number == "WINDOW":
        if scroll_content == 'down':
            driver_task.execute_script(f"window.scrollBy(0, {args.window_height*2//3});")
        else:
            driver_task.execute_script(f"window.scrollBy(0, {-args.window_height*2//3});")
    else:
        if not args.text_only:
            idx = int(scroll_ele_number)
            if idx < 0 or idx >= len(web_eles):
                return
            web_ele = web_eles[idx]
        else:
            element_box = obs_info[int(scroll_ele_number)]['union_bound']
            center = (
                element_box[0] + element_box[2] // 2,
                element_box[1] + element_box[3] // 2
            )
            web_ele = driver_task.execute_script(
                "return document.elementFromPoint(arguments[0], arguments[1]);",
                center[0],
                center[1]
            )
        actions = ActionChains(driver_task)
        driver_task.execute_script("arguments[0].focus();", web_ele)
        if scroll_content == 'down':
            actions.key_down(Keys.ALT).send_keys(Keys.ARROW_DOWN).key_up(Keys.ALT).perform()
        else:
            actions.key_down(Keys.ALT).send_keys(Keys.ARROW_UP).key_up(Keys.ALT).perform()
    time.sleep(3)

def sanitize_messages(messages):
    sanitized = []
    for msg in messages:
        if msg.get("role") == "system":
            msg["content"] = "[系統訊息已隱藏]"
        if isinstance(msg.get("content"), list):
            text_parts = []
            for part in msg["content"]:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            msg["content"] = "\n".join(text_parts)
        sanitized.append(msg)
    return sanitized

# HW2: Orchestration Agent (範例) - 目前程式尚未大幅用到
def call_orchestration_agent(args, client, candidate_thoughts, screenshot_b64, task_goal):
    orchestration_prompt = SYSTEM_ORCHESTRATION_PROMPT + "\n"
    orchestration_prompt += "Thoughts:\n"
    for idx, thought in enumerate(candidate_thoughts):
        orchestration_prompt += f"{idx}. {thought}\n"
    orchestration_prompt += f"Screenshot: [Attached image in base64 format]\nTask Goal: {task_goal}\n"
    messages = [{'role': 'system', 'content': orchestration_prompt}]
    messages = sanitize_messages(messages)
    prompt_tokens, completion_tokens, gpt_call_error, openai_response = call_gpt4v_api(args, client, messages)
    if gpt_call_error or openai_response is None:
        return None
    orchestration_res = openai_response.choices[0].message.content
    logging.info("[Orchestration Agent] " + orchestration_res)
    match = re.search(r"Thought Index:\s*(\d+)", orchestration_res)
    if match:
        return int(match.group(1))
    return None

# Reflection Agent
def call_reflection_agent(args, client, product_results, error_history=None):
    reflection_prompt = (
        "請根據下列產品資訊，考慮各產品的品牌、折扣、星級評分、消費者評論及運費，選出最佳產品，並詳細說明你的理由。\n" #HW3
        "格式如下：\nProduct: <產品名稱>, Website: <網站>, Price: $<價格>\n\n"
        "產品資訊：\n"
    )
    for res in product_results:
        reflection_prompt += (
            f"Product: {res.get('product')}, Website: {res.get('website')}, Price: ${res.get('price')}, "
            f"Brand: {res.get('brand', 'N/A')}, Discount: {res.get('discount', 'N/A')}, Shipping: {res.get('shipping', 'N/A')}\n"
        )
    if error_history:
        reflection_prompt += "\n以下是本次執行的錯誤紀錄，請一併參考：\n"
        for idx, err in enumerate(error_history):
            reflection_prompt += f"{idx}. ErrorType: {err['error_type']}, Iteration: {err['iteration']}, Msg: {err['message']}\n"
    reflection_prompt += "\n請選出最佳產品，並說明你的全鏈式思考。"

    messages = [
        {'role': 'system', 'content': SYSTEM_REFLECTION_PROMPT},
        {'role': 'user', 'content': reflection_prompt}
    ]
    messages = sanitize_messages(messages)
    prompt_tokens, completion_tokens, gpt_call_error, openai_response = call_gpt4v_api(args, client, messages)
    if gpt_call_error or openai_response is None:
        return None
    logging.info("[Reflection Agent] " + openai_response.choices[0].message.content)
    return openai_response.choices[0].message.content

def call_debater_agent(args, client, reflection_answer):
    debater_prompt = (
        "Reflection Answer:\n" + reflection_answer + "\n"
        + "Please respond exactly in the following format:\n"
        + "Debate:\nAccept: Yes    OR    Accept: No\nExplanation: [Your critique]\n"
    )
    messages = [
        {'role': 'system', 'content': DEBATER_AGENT_PROMPT},
        {'role': 'user', 'content': debater_prompt}
    ]
    messages = sanitize_messages(messages)
    prompt_tokens, completion_tokens, gpt_call_error, openai_response = call_gpt4v_api(args, client, messages)
    if gpt_call_error or openai_response is None:
        return None

    debater_response = openai_response.choices[0].message.content
    logging.info("[Debater Agent] " + debater_response)

    accept_pattern = r"Accept:\s*(Yes|No)"
    match = re.search(accept_pattern, debater_response, re.IGNORECASE)
    if match:
        accept_value = match.group(1).strip().lower()  # 'yes' or 'no'
    else:
        accept_value = "unknown"
    return {"full_text": debater_response, "accept": accept_value}

def regenerate_reflection_if_needed(args, client, original_reflection_prompt, product_results, error_history, max_retries):
    retries = 0
    reflection_answer = call_reflection_agent(args, client, product_results, error_history=error_history)
    while retries < max_retries:
        debater_feedback = call_debater_agent(args, client, reflection_answer)
        if debater_feedback and "Rethink" in debater_feedback:
            logging.info("[Debater] Suggests to regenerate Reflection answer.")
            updated_prompt = original_reflection_prompt + "\nDebater Feedback: " + debater_feedback
            reflection_answer = call_reflection_agent(args, client, product_results, error_history=error_history)
            retries += 1
        else:
            break
    return reflection_answer

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_file', type=str, default='data/tasks_test.jsonl')
    parser.add_argument('--max_iter', type=int, default=8)
    # HW2: 新增參數
    parser.add_argument('--trajectory', action='store_true', help='紀錄所有迭代步驟', default='True')
    parser.add_argument('--error_max_reflection_iter', type=int, default=1, help='當迭代過多時，允許的錯誤反思次數')

    parser.add_argument("--api_key", default="key", type=str, help="YOUR_OPENAI_API_KEY")
    parser.add_argument("--api_model", default="gpt-4o-mini", type=str, help="api model name")
    parser.add_argument("--output_dir", type=str, default='results')
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max_attached_imgs", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--download_dir", type=str, default="downloads")
    parser.add_argument("--text_only", action='store_true')
    parser.add_argument("--headless", action='store_true', help='Selenium 瀏覽器視窗')
    parser.add_argument("--save_accessibility_tree", action='store_true')
    parser.add_argument("--force_device_scale", action='store_true')
    parser.add_argument("--window_width", type=int, default=1300)
    parser.add_argument("--window_height", type=int, default=850)
    parser.add_argument("--fix_box_color", action='store_true')
    args = parser.parse_args()

    client = OpenAI(api_key=args.api_key)
    options = driver_config(args)
    current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
    result_dir = os.path.join(args.output_dir, current_time)
    os.makedirs(result_dir, exist_ok=True)

    # HW2: 錯誤紀錄清單
    error_history = []

    # 讀取任務
    tasks = []
    with open(args.test_file, 'r', encoding='utf-8') as f:
        for line in f:
            task = json.loads(line)
            if "websites" not in task:
                task["websites"] = [task["web"]]
            tasks.append(task)

    product_results = []

    activate_EGA = True
    error_exist = False
    EGA_explanation = ""
    bot_thought = ""
    current_history = ""  # 用於記錄每個迭代的 Thought 與 Action
    prev_action = None

    # === 1) Document Processing：把 PDF→向量庫，只做一次 === HW3
    manual_pdf = "data/Amazonjp.pdf"   # 你的操作手冊 PDF
    logger.info("▶ Starting PDF RAG pipeline…")
    pipeline = PDFEnhancementPipeline(
        openai_api_key=args.api_key,
        logger=logging.getLogger(__name__),
        persist_directory="./chroma_db"    # 向量庫存放位置
    )
    logger.info("▶ Processing PDF at %s", manual_pdf)
    pipeline.process_pdf(
        pdf_path=manual_pdf,
        output_dir="manual_output",
        add_image_descriptions=False,      
        rag_mode="overwrite"               # 首次建立，之後想增量就改 append
    )
    logger.info("✔ PDF processing complete")


    for task in tasks:
        #HW3 ----------
        # === 2) Prompt Engineering：透過 RAG search 拿到相關 chunks ===
        prev_intent = "" #留意
        filtered = [
            {k: doc[k] for k in ("section","content","source")}
            for doc in pipeline.search(query=task["ques"], 
                                       k=5,
                                       current_intent=prev_intent,  # 帶入上一步的代理意圖
                                       summarize=True,              # 啟用簡易摘要
                                       return_raw=False)            # 不需要 raw document
        ]
        manual_gen = InstructionManualGenerator(
            openai_api_key=args.api_key,
            task_goal=task["ques"],
            results=filtered,
            logger=logging.getLogger(__name__),
            instruction_format="text_steps"   # 或 "json_blocks"
        )        
        logger.info("▶ Calling InstructionManualGenerator")
        manual_text = manual_gen.generate_instruction_manual()
        logger.info("✔ Received manual text (first 100 chars): %s", manual_text[:100].replace("\n", " "))

        # 把手冊加到 init_msg 前面
        #init_msg = f"[Instruction Manual]\n{manual_text}\n\n" + init_msg
        #HW3 ----------
        
        task_dir = os.path.join(result_dir, 'task{}'.format(task["id"]))
        os.makedirs(task_dir, exist_ok=True)
        setup_logger(task_dir)
        logging.info(f'########## TASK {task["id"]} ##########')
        logging.info(f"The manual text is {manual_text}")

        product = task.get("product", "Apple iPhone 12 Pro Max (256GB, Pacific Blue)")
        for website in task["websites"]:
            args.trajectory = True
            if website == "https://www.amazon.com/":
                # 這邊只是例子，Amazon就關閉trajectory
                args.trajectory = False

            
            current_history = SYSTEM_PREVIOUS_STEP
            logging.info(f"[Main] Processing website: {website}")
            driver_task = webdriver.Chrome(options=options)
            driver_task.set_window_size(args.window_width, args.window_height)
            driver_task.get(website)

            refresh_count = 0
            if not wait_for_page_load(driver_task, timeout=20):
                while refresh_count < 3 and not wait_for_page_load(driver_task, timeout=20):
                    logging.info(f"[Main] Page not fully loaded on {website}, refreshing... (Count: {refresh_count+1})")
                    exec_action_refresh(driver_task)
                    refresh_count += 1
                if refresh_count >= 3:
                    logging.error(f"[Main] Page failed to load after 3 refreshes on {website}. Skipping.")
                    driver_task.quit()
                    continue
            time.sleep(5)

            try:
                driver_task.find_element(By.TAG_NAME, 'body').click()
            except:
                pass

            driver_task.execute_script(
                """window.onkeydown = function(e) {
                     if(e.keyCode == 32 && e.target.type != 'text'
                        && e.target.type != 'textarea'
                        && e.target.type != 'search') {
                         e.preventDefault();
                     }
                };"""
            )
            time.sleep(5)
            driver_task.execute_script(
                "var overlays = document.querySelectorAll('div[style*=\"z-index: 2147483647\"]');"
                "for(var i=0;i<overlays.length;i++){ overlays[i].remove(); }"
            )
            for filename in os.listdir(args.download_dir):
                file_path = os.path.join(args.download_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            download_files = []

            fail_obs = ""
            pdf_obs = ""
            warn_obs = ""
            pattern = r'Thought:|Action:|Observation:|Errors:|Explanation:'

            # 初始系統訊息
            messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
            obs_prompt = "Observation: please analyze the attached screenshot and give the Thought and Action."
            if args.text_only:
                messages = [{'role': 'system', 'content': SYSTEM_PROMPT_TEXT_ONLY}]
                obs_prompt = "Observation: please analyze the accessibility tree and give the Thought and Action."

             # 4) 合併一次性地組裝 init_msg：先手冊，再任務說明，最後是觀察提示 HW3
            init_msg = (
                 "[Instruction Manual]\n"
                 + manual_text
                 + "\n\n"  # 與任務說明分隔
                 + f"Now given a task: {task['ques']} On website {website}, "
                   f"search for the product '{product}' and extract its product name, website and price "
                   "in the format: Product: <Product_Name>, Website: <Website>, Price: $<Price>.\n"
                 + "You MUST scroll through the product listings for at least one full page to gather sufficient information.\n"
                 + obs_prompt
            )

            it = 0
            accumulate_prompt_token = 0
            accumulate_completion_token = 0
            bot_thought = ""
            prev_action = None
            repeat_counter = 0

            while it < args.max_iter:
                logging.info(f"[Main] Iteration: {it} for website {website}")
                it += 1

                if not fail_obs:
                    try:
                        if not args.text_only:
                            rects, web_eles, web_eles_text = get_web_element_rect(
                                driver_task, fix_color=args.fix_box_color
                            )
                        else:
                            accessibility_tree_path = os.path.join(task_dir, f'accessibility_tree_{it}')
                            ac_tree, obs_info = get_webarena_accessibility_tree(
                                driver_task, accessibility_tree_path
                            )
                    except Exception as e:
                        logging.error("[Main] Driver error when obtaining elements or accessibility tree.")
                        logging.error(e)
                        error_history.append({
                            "error_type": "get_element_error",
                            "iteration": it,
                            "message": str(e)
                        })
                        break

                    time.sleep(2)
                    img_path = os.path.join(
                        task_dir,
                        f'screenshot_{website.replace("https://", "").replace("/", "_")}_{it}.png'
                    )
                    driver_task.save_screenshot(img_path)
                    driver_task.execute_script(
                        "var overlays = document.querySelectorAll('div[style*=\"z-index: 2147483647\"]');"
                        "for(var i=0;i<overlays.length;i++){ overlays[i].remove(); }"
                    )
                    if (not args.text_only) and args.save_accessibility_tree:
                        accessibility_tree_path = os.path.join(
                            task_dir,
                            f"accessibility_tree_{website.replace('https://', '').replace('/', '_')}_{it}"
                        )
                        get_webarena_accessibility_tree(driver_task, accessibility_tree_path)
                    b64_img = encode_image(img_path)

                    # HW2 EGA（Error Grounding Agent）
                    if it > 1 and activate_EGA:
                        EGA_messages = [{'role': 'system', 'content': ERROR_GROUNDING_AGENT_PROMPT}]
                        EGA_img = encode_image(img_path)
                        EGA_user_message = {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': 'Thought:' + bot_thought + '\nScreenshot:'},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{EGA_img}"}}
                            ]
                        }
                        EGA_messages.append(EGA_user_message)
                        pt, ct, err, openai_response = call_gpt4v_api(args, client, EGA_messages)
                        if err:
                            break
                        else:
                            accumulate_prompt_token += pt
                            accumulate_completion_token += ct
                            logging.info('[EGA] : API call complete.')
                        EGA_res = openai_response.choices[0].message.content
                        parts = re.split(pattern, EGA_res)
                        if len(parts) >= 3 and parts[1].strip() == 'Yes':
                            error_exist = True
                            EGA_explanation = parts[2].strip()
                        else:
                            error_exist = False
                            EGA_explanation = ""
                        logging.info(f"Error : {parts[1].strip()}，Explanation : {parts[2].strip()}")
                    else:
                        error_exist = False
                        EGA_explanation = ""

                    if not args.text_only:
                        add_info = ""
                        if error_exist:
                            add_info = (
                                "\nAdditional Information: Looks like your previous thought has some problem in operation. EGA says:\n"
                                + EGA_explanation
                            )
                        curr_msg = format_msg(
                            it,
                            init_msg,
                            pdf_obs,
                            warn_obs,
                            b64_img,
                            web_eles_text,
                            prev_step_action=current_history + add_info
                        )
                    else:
                        add_info = ""
                        if error_exist:
                            add_info = "\nAdditional Information: " + EGA_explanation
                        curr_msg = format_msg_text_only(
                            it,
                            init_msg,
                            pdf_obs,
                            warn_obs,
                            ac_tree,
                            prev_step_action=current_history + add_info
                        )
                    messages.append(curr_msg)
                else:
                    messages.append({'role': 'user', 'content': fail_obs})

                if not args.text_only:
                    messages = clip_message_and_obs(messages, args.max_attached_imgs)
                else:
                    messages = clip_message_and_obs_text_only(messages, args.max_attached_imgs)

                pt, ct, err, openai_response = call_gpt4v_api(args, client, messages)
                time.sleep(1)
                if err:
                    error_history.append({
                        "error_type": "gpt_call_error",
                        "iteration": it,
                        "message": "GPT-4o API call error"
                    })
                    break

                accumulate_prompt_token += pt
                accumulate_completion_token += ct
                logging.info(f"[Main] Accumulated Prompt Tokens: {accumulate_prompt_token}; Completion Tokens: {accumulate_completion_token}")

                if openai_response is None or not openai_response.choices:
                    error_history.append({
                        "error_type": "no_response",
                        "iteration": it,
                        "message": "No GPT response."
                    })
                    break

                gpt_4v_res = openai_response.choices[0].message.content
                messages.append({'role': 'assistant', 'content': gpt_4v_res})
                logging.info("[GPT-4o-mini] " + gpt_4v_res)

                try:
                    assert 'Thought:' in gpt_4v_res and 'Action:' in gpt_4v_res
                except AssertionError:
                    fail_obs = "Format ERROR: Both 'Thought' and 'Action' must be included in your reply."
                    error_history.append({
                        "error_type": "format_missing_thought_action",
                        "iteration": it,
                        "message": fail_obs
                    })
                    continue

                # 分離 Thought 與 Action
                parts = re.split(pattern, gpt_4v_res)
                primary_thought = parts[1].strip() if len(parts) > 1 else ""
                chosen_action = parts[2].strip() if len(parts) > 2 else ""
                bot_thought = primary_thought

                # HW2 檢查是否連續動作相同，下一個動作會考量(近兩次)History
                if primary_thought and chosen_action.strip().lower() == primary_thought.strip().lower():
                    repeat_counter += 1
                    logging.info("[Main] Detected repeated action.")
                    if repeat_counter >= 2:
                        logging.info("[Main] Repeated action threshold => resetting current_history.")
                        current_history = SYSTEM_PREVIOUS_STEP + "\nHint: Try a different approach instead of repeating."
                        repeat_counter = 0
                else:
                    if args.trajectory:
                        current_history += (
                            f"\nThought: {bot_thought}\nAction: {chosen_action}"
                            f"\nError: {error_exist}\nExplanation: {EGA_explanation}\n"
                        )
                    repeat_counter = 0
                primary_thought = chosen_action

                # 解析 action_key
                action_key, info = extract_information(gpt_4v_res)
                if action_key == "format_error":
                    fail_obs = info["content"]
                    error_history.append({
                        "error_type": "response_format_error",
                        "iteration": it,
                        "message": fail_obs
                    })
                    logging.error(f"[GPT-4o-mini] Response format error: {fail_obs}")
                    continue
                fail_obs = ""

                # 如果到最後一輪了，但還不是 'answer'，就強迫代理人給最終答案
                '''if it  == args.max_iter and action_key != 'answer':
                    fail_obs = (
                        "You have reached the maximum iteration, you must produce a final answer in Action: Answer format."
                        " Please do so now."
                    )
                    logging.info("[Main] Forcing final answer because max iteration is reached.")
                    continue'''


                pdf_obs = ""
                warn_obs = ""

                # 執行對應的動作
                try:
                    driver_task.switch_to.window(driver_task.current_window_handle)
                    if action_key == 'click':
                        try:
                            idx = int(info[0])
                            if not args.text_only:
                                if idx < 0 or idx >= len(web_eles):
                                    fail_obs = "Invalid numerical label for click action."
                                    logging.error(f"[GPT-4o-mini] {fail_obs}")
                                    error_history.append({
                                        "error_type": "invalid_click_index",
                                        "iteration": it,
                                        "message": fail_obs
                                    })
                                    continue
                                web_ele = web_eles[idx]
                            else:
                                if idx < 0 or idx >= len(obs_info):
                                    fail_obs = "Invalid numerical label for click action."
                                    logging.error(f"[GPT-4o-mini] {fail_obs}")
                                    error_history.append({
                                        "error_type": "invalid_click_index",
                                        "iteration": it,
                                        "message": fail_obs
                                    })
                                    continue
                                element_box = obs_info[idx]['union_bound']
                                center = (
                                    element_box[0] + element_box[2] // 2,
                                    element_box[1] + element_box[3] // 2
                                )
                                web_ele = driver_task.execute_script(
                                    "return document.elementFromPoint(arguments[0], arguments[1]);",
                                    center[0], center[1]
                                )

                            exec_action_click(info, web_ele, driver_task)
                        except Exception as e:
                            if "stale element reference" in str(e).lower():
                                logging.info("[GPT-4o-mini] Stale element reference => re-fetch elements.")
                                error_history.append({
                                    "error_type": "stale_reference",
                                    "iteration": it,
                                    "message": str(e)
                                })
                                rects, web_eles, web_eles_text = get_web_element_rect(
                                    driver_task, fix_color=args.fix_box_color
                                )
                                idx = int(info[0])
                                # 再執行一次
                                if not args.text_only:
                                    if idx < 0 or idx >= len(web_eles):
                                        fail_obs = "Invalid numerical label for click action."
                                        logging.error(f"[GPT-4o-mini] {fail_obs}")
                                        error_history.append({
                                            "error_type": "invalid_click_index",
                                            "iteration": it,
                                            "message": fail_obs
                                        })
                                        continue
                                    web_ele = web_eles[idx]
                                else:
                                    if idx < 0 or idx >= len(obs_info):
                                        fail_obs = "Invalid numerical label for click action."
                                        logging.error(f"[GPT-4o-mini] {fail_obs}")
                                        error_history.append({
                                            "error_type": "invalid_click_index",
                                            "iteration": it,
                                            "message": fail_obs
                                        })
                                        continue
                                    element_box = obs_info[idx]['union_bound']
                                    center = (
                                        element_box[0] + element_box[2] // 2,
                                        element_box[1] + element_box[3] // 2
                                    )
                                    web_ele = driver_task.execute_script(
                                        "return document.elementFromPoint(arguments[0], arguments[1]);",
                                        center[0], center[1]
                                    )
                                exec_action_click(info, web_ele, driver_task)
                            else:
                                error_history.append({
                                    "error_type": "click_exception",
                                    "iteration": it,
                                    "message": str(e)
                                })
                                raise e

                        current_files = sorted(os.listdir(args.download_dir))
                        if current_files != download_files:
                            time.sleep(10)
                            current_files = sorted(os.listdir(args.download_dir))
                            new_pdf = [
                                f for f in current_files
                                if f not in download_files and f.endswith('.pdf')
                            ]
                            if new_pdf:
                                pdf_file = new_pdf[0]
                                pdf_obs = get_pdf_retrieval_ans_from_assistant(
                                    client,
                                    os.path.join(args.download_dir, pdf_file),
                                    task['ques']
                                )
                                shutil.copy(
                                    os.path.join(args.download_dir, pdf_file),
                                    task_dir
                                )
                                pdf_obs = "Downloaded PDF. Assistant API response: " + pdf_obs
                            download_files = current_files

                        # type='submit'
                        if web_ele.tag_name.lower() == 'button' and web_ele.get_attribute("type") == 'submit':
                            time.sleep(10)

                    elif action_key == 'wait':
                        # 有時代理人會寫 Wait 2s, Wait for captcha => 直接做短暫等待
                        time.sleep(5)

                    elif action_key == 'type':
                        idx = int(info['number'])
                        if not args.text_only:
                            if idx < 0 or idx >= len(web_eles):
                                fail_obs = "Invalid numerical label for type action."
                                logging.error(f"[GPT-4o-mini] {fail_obs}")
                                error_history.append({
                                    "error_type": "invalid_type_index",
                                    "iteration": it,
                                    "message": fail_obs
                                })
                                continue
                            web_ele = web_eles[idx]
                        else:
                            if idx < 0 or idx >= len(obs_info):
                                fail_obs = "Invalid numerical label for type action."
                                logging.error(f"[GPT-4o-mini] {fail_obs}")
                                error_history.append({
                                    "error_type": "invalid_type_index",
                                    "iteration": it,
                                    "message": fail_obs
                                })
                                continue
                            element_box = obs_info[idx]['union_bound']
                            center = (
                                element_box[0] + element_box[2] // 2,
                                element_box[1] + element_box[3] // 2
                            )
                            web_ele = driver_task.execute_script(
                                "return document.elementFromPoint(arguments[0], arguments[1]);",
                                center[0], center[1]
                            )
                        warn_obs = exec_action_type(info, web_ele, driver_task)

                    elif action_key == 'scroll':
                        exec_action_scroll(
                            info, web_eles, driver_task,
                            args,
                            obs_info if args.text_only else None
                        )
                    elif action_key == 'goback':
                        driver_task.back()
                        time.sleep(2)
                    elif action_key == 'google':
                        driver_task.get('https://www.google.com/')
                        time.sleep(2)
                    elif action_key == 'refresh':
                        logging.info("[GPT-4o-mini] Executing Refresh action.")
                        exec_action_refresh(driver_task)
                    elif action_key == 'zoom':
                        logging.info(f"[GPT-4o-mini] Executing Zoom with parameter: {info['content']}")
                        exec_action_zoom(info, driver_task)
                    elif action_key == 'answer':
                        logging.info("[GPT-4o-mini] Final answer action received.")
                        break
                    else:
                        error_history.append({
                            "error_type": "not_implemented_action",
                            "iteration": it,
                            "message": f"Action {action_key} not implemented."
                        })
                        raise NotImplementedError

                    fail_obs = ""
                except Exception as e:
                    logging.error("[GPT-4o-mini] Driver error:")
                    logging.error(e)
                    if 'element click intercepted' not in str(e):
                        fail_obs = (
                            "The chosen action cannot be executed. Check if the numerical label or action format is wrong. "
                            "Then provide revised Thought and Action."
                        )
                        error_history.append({
                            "error_type": "driver_error",
                            "iteration": it,
                            "message": str(e)
                        })
                    else:
                        fail_obs = ""
                    time.sleep(2)

            # 關閉瀏覽器
            driver_task.quit()

            # 將本次網站的互動 messages 做一次整理，嘗試擷取最終 Product 資訊
            product_result_temp = print_message(messages, task_dir, website)
            if product_result_temp:
                if "brand" not in product_result_temp or product_result_temp["brand"] in ["N/A", "品牌資訊待補"]:
                    product_result_temp["brand"] = (
                        product_result_temp["product"].split()[0]
                        if product_result_temp["product"].split() else "品牌資訊待補"
                    )
                product_results.append(product_result_temp)
                logging.info(f"[Main] Website {website} result: {product_result_temp}")
            else:
                logging.info(f"[Main] No valid product result for website: {website}")

        # HW2 若本任務收集到任何商品結果，則呼叫 Reflection Agent、Debater Agent
        if product_results:
            reflection_response = call_reflection_agent(
                args, client, product_results,
                error_history=error_history
            )

            if reflection_response:
                logging.info("[Main] Reflection Agent responsed")

                debater_result = call_debater_agent(args, client, reflection_response)
                if debater_result:
                    logging.info("[Main] Debater Agent responsed")

                    if debater_result["accept"] == "yes":
                        logging.info("[Main] Debater says Accept: Yes => Final answer accepted.")
                    elif debater_result["accept"] == "no":
                        logging.info("[Main] Debater says Accept: No => Re-run Reflection.")
                        reflection_response = call_reflection_agent(
                            args, client, product_results,
                            error_history=error_history
                        ) # 重新呼叫reflection_agent 1次 未來改成 regenerate_reflection_if_needed
                        logging.info("[Main] Revised Reflection Agent responsed")
                    else:
                        logging.info("[Main] Debater parse error or unknown accept => skip re-run.")
                else:
                    logging.info("[Main] No debater feedback provided.")
            else:
                logging.error("[Main] Reflection Agent API call failed.")
        else:
            logging.info(f"[Main] No valid product results for task: {task['id']}")

if __name__ == '__main__':
    main()
    print('End of process')
