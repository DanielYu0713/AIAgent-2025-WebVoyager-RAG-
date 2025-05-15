import base64
import re
import os
import json
import time
import logging
import numpy as np
from PIL import Image

from utils_webarena import (
    fetch_browser_info, 
    fetch_page_accessibility_tree, 
    parse_accessibility_tree, 
    clean_accesibility_tree
)

def resize_image(image_path):
    image = Image.open(image_path)
    width, height = image.size
    if min(width, height) < 512:
        return image
    elif width < height:
        new_width = 512
        new_height = int(height * (new_width / width))
    else:
        new_height = 512
        new_width = int(width * (new_height / height))
    resized_image = image.resize((new_width, new_height), Image.LANCZOS)
    resized_image.save(image_path)

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# HW2 Fix: Scroll 要同時接受 "Scroll [1]; down" 和 "Scroll down; [1]"
def extract_information(text):
    text = text.strip()
    # 如果回應中存在 "Action:" 但缺少 "Thought:"，則補上空的 Thought 部分
    if "Action:" in text and "Thought:" not in text:
        text = "Thought: \n" + text

        
    # 先嘗試匹配 "Scroll 1; down"
    patternA = r"Scroll\s*\[?(\d+|WINDOW)\]?[;: ]+\[?(up|down).*?$"
    # 再嘗試匹配 "Scroll down; [1]"
    patternB = r"Scroll\s*(up|down)\s*[;: ]+\[?(\d+|WINDOW)\]?.*$"

    # 其餘動作保持不變
    patterns_others = {
        "click": r"Click\s*\[?(\d+)\]?",
        "type": r"Type\s*\[?(\d+)\]?[;: ]+\[?(.*?)\]?$",
        "wait": r"^Wait\b",
        "goback": r"^GoBack\b",
        "google": r"^Google\b",
        "answer": r"(?:Answer|ANSWER)[;: ]+\s*(.*)$",
        "refresh": r"^Refresh\b",
        "zoom": r"Zoom\s*\[?([^\]]+)\]?"
    }

    # 先檢查 scrollA
    matchA = re.search(patternA, text, re.IGNORECASE|re.DOTALL)
    if matchA:
        number = matchA.group(1)
        direction = matchA.group(2)
        return "scroll", {"number": number, "content": direction}

    # 再檢查 scrollB
    matchB = re.search(patternB, text, re.IGNORECASE|re.DOTALL)
    if matchB:
        direction = matchB.group(1)
        number = matchB.group(2)
        return "scroll", {"number": number, "content": direction}

    # 其餘動作
    for key, pattern in patterns_others.items():
        m = re.search(pattern, text, re.IGNORECASE|re.DOTALL)
        if m:
            if key in ["click", "wait", "goback", "google", "refresh"]:
                return key, m.groups()
            elif key == "type":
                return key, {"number": m.group(1), "content": m.group(2)}
            elif key == "zoom":
                return key, {"content": m.group(1)}
            elif key == "answer":
                content = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
                return key, {"content": content.strip()}

    return "format_error", {"content": "無法解析 GPT 回應格式，請檢查輸入"}

def get_web_element_rect(browser, fix_color=True):
    if fix_color:
        selected_function = "getFixedColor"
    else:
        selected_function = "getRandomColor"

    js_script = """
    let labels = [];

    function markPage() {
        var bodyRect = document.body.getBoundingClientRect();
        var items = Array.prototype.slice.call(
            document.querySelectorAll('*')
        ).map(function(element) {
            var vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
            var vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
            
            var rects = [...element.getClientRects()].filter(bb => {
                var center_x = bb.left + bb.width / 2;
                var center_y = bb.top + bb.height / 2;
                var elAtCenter = document.elementFromPoint(center_x, center_y);
                return elAtCenter === element || element.contains(elAtCenter);
            }).map(bb => {
                const rect = {
                    left: Math.max(0, bb.left),
                    top: Math.max(0, bb.top),
                    right: Math.min(vw, bb.right),
                    bottom: Math.min(vh, bb.bottom)
                };
                return {
                    ...rect,
                    width: rect.right - rect.left,
                    height: rect.bottom - rect.top
                }
            });
            var area = rects.reduce((acc, rect) => acc + rect.width * rect.height, 0);
            return {
                element: element,
                include: 
                    (element.tagName === "INPUT" || element.tagName === "TEXTAREA" || element.tagName === "SELECT") ||
                    (element.tagName === "BUTTON" || element.tagName === "A" || (element.onclick != null) || window.getComputedStyle(element).cursor == "pointer") ||
                    (element.tagName === "IFRAME" || element.tagName === "VIDEO" || element.tagName === "LI" || element.tagName === "TD" || element.tagName === "OPTION"),
                area,
                rects,
                text: element.textContent.trim().replace(/\s{2,}/g, ' ')
            };
        }).filter(item =>
            item.include && (item.area >= 20)
        );
        const buttons = Array.from(document.querySelectorAll('button, a, input[type="button"], div[role="button"]'));
        items = items.filter(x => !buttons.some(y => items.some(z => z.element === y) && y.contains(x.element) && !(x.element === y) ));
        items = items.filter(x => 
            !(x.element.parentNode && 
            x.element.parentNode.tagName === 'SPAN' && 
            x.element.parentNode.children.length === 1 && 
            x.element.parentNode.getAttribute('role') &&
            items.some(y => y.element === x.element.parentNode)));
        items = items.filter(x => !items.some(y => x.element.contains(y.element) && !(x == y)));

        function getRandomColor(index) {
            var letters = '0123456789ABCDEF';
            var color = '#';
            for (var i = 0; i < 6; i++) {
                color += letters[Math.floor(Math.random() * 16)];
            }
            return color;
        }
        function getFixedColor(index) {
            var color = '#000000'
            return color
        }

        items.forEach(function(item, index) {
            item.rects.forEach((bbox) => {
                newElement = document.createElement("div");
                var borderColor = COLOR_FUNCTION(index);
                newElement.style.outline = `2px dashed ${borderColor}`;
                newElement.style.position = "fixed";
                newElement.style.left = bbox.left + "px";
                newElement.style.top = bbox.top + "px";
                newElement.style.width = bbox.width + "px";
                newElement.style.height = bbox.height + "px";
                newElement.style.pointerEvents = "none";
                newElement.style.boxSizing = "border-box";
                newElement.style.zIndex = 2147483647;
                
                var label = document.createElement("span");
                label.textContent = index;
                label.style.position = "absolute";
                label.style.top = Math.max(-19, -bbox.top) + "px";
                label.style.left = Math.min(Math.floor(bbox.width / 5), 2) + "px";
                label.style.background = borderColor;
                label.style.color = "white";
                label.style.padding = "2px 4px";
                label.style.fontSize = "12px";
                label.style.borderRadius = "2px";
                newElement.appendChild(label);
                
                document.body.appendChild(newElement);
                labels.push(newElement);
            })
        })
        return [labels, items]
    }
    return markPage();
    """.replace("COLOR_FUNCTION", selected_function)

    rects, items_raw = browser.execute_script(js_script)
    format_ele_text = []
    for web_ele_id in range(len(items_raw)):
        label_text = items_raw[web_ele_id]['text']
        ele_tag_name = items_raw[web_ele_id]['element'].tag_name
        ele_type = items_raw[web_ele_id]['element'].get_attribute("type")
        ele_aria_label = items_raw[web_ele_id]['element'].get_attribute("aria-label")
        input_attr_types = ['text', 'search', 'password', 'email', 'tel']

        if not label_text:
            if (ele_tag_name.lower() == 'input' and ele_type in input_attr_types) or ele_tag_name.lower() == 'textarea' or (ele_tag_name.lower() == 'button' and ele_type in ['submit', 'button']):
                if ele_aria_label:
                    format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{ele_aria_label}\";")
                else:
                    format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"\";")
        elif label_text and len(label_text) < 200:
            if not ("<img" in label_text and "src=" in label_text):
                if ele_tag_name in ["button", "input", "textarea"]:
                    if ele_aria_label and (ele_aria_label != label_text):
                        format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{label_text}\", \"{ele_aria_label}\";")
                    else:
                        format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{label_text}\";")
                else:
                    if ele_aria_label and (ele_aria_label != label_text):
                        format_ele_text.append(f"[{web_ele_id}]: \"{label_text}\", \"{ele_aria_label}\";")
                    else:
                        format_ele_text.append(f"[{web_ele_id}]: \"{label_text}\";")

    format_ele_text = '\t'.join(format_ele_text)
    return rects, [web_ele['element'] for web_ele in items_raw], format_ele_text

def clip_message_and_obs(msg, max_img_num):
    clipped_msg = []
    img_num = 0
    for idx in range(len(msg)):
        curr_msg = msg[len(msg) - 1 - idx]
        if curr_msg['role'] != 'user':
            clipped_msg = [curr_msg] + clipped_msg
        else:
            if isinstance(curr_msg['content'], str):
                clipped_msg = [curr_msg] + clipped_msg
            elif img_num < max_img_num:
                img_num += 1
                clipped_msg = [curr_msg] + clipped_msg
            else:
                msg_no_pdf = curr_msg['content'][0]["text"].split("Observation:")[0].strip() + "Observation: A screenshot and some texts. (Omitted in context.)"
                msg_pdf = curr_msg['content'][0]["text"].split("Observation:")[0].strip() + "Observation: A screenshot, a PDF file and some texts. (Omitted in context.)"
                curr_msg_clip = {
                    'role': curr_msg['role'],
                    'content': msg_no_pdf if "You downloaded a PDF file" not in curr_msg['content'][0]["text"] else msg_pdf
                }
                clipped_msg = [curr_msg_clip] + clipped_msg
    return clipped_msg

def clip_message_and_obs_text_only(msg, max_tree_num):
    clipped_msg = []
    tree_num = 0
    for idx in range(len(msg)):
        curr_msg = msg[len(msg) - 1 - idx]
        if curr_msg['role'] != 'user':
            clipped_msg = [curr_msg] + clipped_msg
        else:
            if tree_num < max_tree_num:
                tree_num += 1
                clipped_msg = [curr_msg] + clipped_msg
            else:
                msg_no_pdf = curr_msg['content'].split("Observation:")[0].strip() + "Observation: An accessibility tree. (Omitted in context.)"
                msg_pdf = curr_msg['content'].split("Observation:")[0].strip() + "Observation: An accessibility tree and a PDF file. (Omitted in context.)"
                curr_msg_clip = {
                    'role': curr_msg['role'],
                    'content': msg_no_pdf if "You downloaded a PDF file" not in curr_msg['content'] else msg_pdf
                }
                clipped_msg = [curr_msg_clip] + clipped_msg
    return clipped_msg

def convert_price_to_twd(price_str, response_text, raw_price_with_symbol=""):
    conversion_rate = 30 # default: USD
    if any(sym in response_text for sym in ["€", "EUR"]):
        conversion_rate = 35
    elif any(sym in response_text + raw_price_with_symbol for sym in ["¥", "￥", "円", "JPY", "Amazon.co.jp"]):
        conversion_rate = 0.23
    elif any(sym in response_text for sym in ["人民幣", "RMB", "CNY"]):
        conversion_rate = 4.5
    try:
        original_price = float(price_str)
        return round(original_price * conversion_rate, 2)
    except Exception:
        return price_str

def print_message(json_object, save_dir=None, website=None):
    remove_b64code_obj = []
    for obj in json_object:
        if obj['role'] == 'system':
            continue
        remove_b64code_obj.append(obj)

    product_result = None
    pattern = r"Product:\s*(.+?),\sWebsite:\s(.+?),\sPrice:\s[$\￥\円]?([\d,]+(?:.\d{1,2})?)(?:[$\￥\円])?(?:.)?"
    for obj in reversed(json_object):
        if obj['role'] == 'assistant':
            action_key, info = extract_information(obj['content'])
            if action_key == "answer":
                match = re.search(pattern, info['content'])
                if match:
                    product_name = match.group(1).strip()
                    website_str = match.group(2).strip()
                    
                    price_str_raw = match.group(3).strip()
                    price_str = price_str_raw.replace(',', '').replace('￥', '').replace('¥', '')
                    price_twd = convert_price_to_twd(price_str, obj['content'], price_str_raw)

                    inferred_brand = product_name.split()[0] if product_name.split() else "品牌資訊待補"
                    product_result = {
                        "website": website_str,
                        "product": product_name,
                        "price": price_twd,
                        "brand": inferred_brand,
                        "response": obj['content']
                    }
                else:
                    logging.error("[Print_Message] Failed to extract product result using pattern: %s" % pattern)
                break

    if save_dir:
        with open(os.path.join(save_dir, 'interact_messages.json'), 'w', encoding='utf-8') as fw:
            json.dump(remove_b64code_obj, fw, indent=2)
    return product_result

def get_webarena_accessibility_tree(browser, save_file=None):
    browser_info = fetch_browser_info(browser)
    accessibility_tree = fetch_page_accessibility_tree(browser_info, browser, current_viewport_only=True)
    content, obs_nodes_info = parse_accessibility_tree(accessibility_tree)
    content = clean_accesibility_tree(content)
    if save_file:
        with open(save_file + '.json', 'w', encoding='utf-8') as fw:
            json.dump(obs_nodes_info, fw, indent=2)
        with open(save_file + '.txt', 'w', encoding='utf-8') as fw:
            fw.write(content)
    return content, obs_nodes_info

def compare_images(img1_path, img2_path):
    img1 = Image.open(img1_path)
    img2 = Image.open(img2_path)
    img1_array = np.asarray(img1)
    img2_array = np.asarray(img2)
    difference = np.abs(img1_array - img2_array)
    total_difference = np.sum(difference)
    return total_difference

def get_pdf_retrieval_ans_from_assistant(client, pdf_path, task):
    logging.info("[Assistant API] You download a PDF file that will be retrieved using the Assistant API.")
    file = client.files.create(
        file=open(pdf_path, "rb"),
        purpose='assistants'
    )
    logging.info("[Assistant API] Create assistant...")
    assistant = client.beta.assistants.create(
        instructions="You are a helpful assistant that can analyze the content of a PDF file and give an answer that matches the given task, or retrieve relevant content that matches the task.",
        model="gpt-4-1106-preview",
        tools=[{"type": "retrieval"}],
        file_ids=[file.id]
    )
    thread = client.beta.threads.create()
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=task,
        file_ids=[file.id]
    )
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )
    while True:
        run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run_status.status == 'completed':
            break
        time.sleep(2)
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    messages_text = messages.data[0].content[0].text.value
    file_deletion_status = client.beta.assistants.files.delete(
        assistant_id=assistant.id,
        file_id=file.id
    )
    logging.info("[Assistant API] " + str(file_deletion_status))
    assistant_deletion_status = client.beta.assistants.delete(assistant.id)
    logging.info("[Assistant API] " + str(assistant_deletion_status))
    return messages_text

