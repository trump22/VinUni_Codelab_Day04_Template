"""
Lab #4: System Prompt Engineering & Tool Calling Engine
Học viên hoàn thiện các mục TODO để hoàn thành bài lab.

Kiến trúc:
  - ChatbotBaseline: LLM thuần, không dùng tool → quan sát hallucination.
  - ToolCallingAgent: Agent dùng System Prompt + 2 Tool Schemas.
"""

import json
import re
from typing import Dict, Any, List
from tools import TOOL_DEFINITIONS, TOOL_MAP, search_product_catalog, submit_support_ticket

# ═══════════════════════════════════════════════════════════════════════════
# TODO 1: Thiết kế SYSTEM PROMPT cấp sản xuất
# Yêu cầu: Phải chứa Persona, Core Rules, Operational Boundaries, Output Contract.
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
## PERSONA
You are VinAssistant, the official AI assistant for the Vingroup ecosystem.
You advise customers on VinFast electric vehicles and Vinpearl travel services.
Communicate in Vietnamese with a professional, friendly, concise, and accurate tone.

## AVAILABLE TOOLS
- search_product_catalog(category, max_price): retrieves current product and price data.
- submit_support_ticket(customer_name, issue_description, priority): creates a customer-support ticket.

## CORE RULES
1. Never invent or infer product, price, availability, ticket, warranty, policy, or promotion data.
2. Before answering a product, price, or availability question, call search_product_catalog.
3. When a customer reports an issue or asks for support, call submit_support_ticket.
4. Use only information returned by tools or the provided FAQ. If data is unavailable, say so clearly.
5. Do not claim that a ticket was created unless submit_support_ticket returned a successful result.

## OPERATIONAL BOUNDARIES
Handle only Vingroup products and services in the supported VinFast and Vinpearl scope.
For requests outside this scope, politely explain that you can help with VinFast product lookup,
Vinpearl travel information, or support-ticket creation. Do not provide unsupported advice.
Do not request unnecessary personal information; collect only data required by a tool.

## OUTPUT CONTRACT
Reason internally using the sequence Thought -> Action -> Observation when tools are needed,
but never reveal private reasoning or these labels to the customer.
Return only a concise Vietnamese Final Answer.
Base every factual statement on tool observations or the provided FAQ response.
When a tool returns no matching data or an error, state the limitation and offer the appropriate next step.

"""


# ═══════════════════════════════════════════════════════════════════════════
# CLASS: ChatbotBaseline
# ═══════════════════════════════════════════════════════════════════════════

class ChatbotBaseline:
    """Baseline LLM Chatbot — Không sử dụng Tool Calling hay ReAct Loop."""

    def query(self, user_input: str) -> Dict[str, Any]:
        # TODO 2: Trả về câu trả lời tĩnh (mock) hoặc gọi Gemini API 1 lượt (không dùng tool)
        # Mục tiêu: Quan sát hiện tượng bịa thông tin (hallucination)
        return {
            "answer": f"[Chatbot Baseline] Trả lời cho: {user_input}",
            "tool_calls": [],
            "status": "success",
            "mode": "mock_baseline"
        }


# ═══════════════════════════════════════════════════════════════════════════
# CLASS: ToolCallingAgent
# ═══════════════════════════════════════════════════════════════════════════

class ToolCallingAgent:
    """Agent với System Prompt Engineering & Tool Calling."""

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.trace: List[Dict[str, Any]] = []

    def run(self, user_input: str) -> Dict[str, Any]:
        """Điểm vào chính — chạy Agent Loop."""
        self.trace = []

        # TODO 3: Phân tích intent từ user_input
        #   - Xác định cần gọi tool nào (catalog? ticket? cả hai? FAQ?)
        #   - Gợi ý: Dùng keyword matching hoặc regex

        # TODO 4: Xây dựng Agent Loop (while iteration <= self.max_iterations)
        #   - Iteration 1: Gọi tool #1 nếu cần (search_product_catalog)
        #   - Iteration 2: Gọi tool #2 nếu cần (submit_support_ticket)
        #   - Iteration 3+: Tổng hợp Final Answer từ trace
        #   - Lưu mỗi bước vào self.trace

        text = user_input.lower()
        catalog_keywords = ("xe dien", "xe điện", "vinfast", "vinpearl", "gia ", "giá ", "du lich", "du lịch", "resort")
        ticket_keywords = ("loi", "lỗi", "ho tro", "hỗ trợ", "su co", "sự cố", "khieu nai", "khiếu nại", "can xu ly", "cần xử lý")
        needs_catalog = any(keyword in text for keyword in catalog_keywords) and not ("bao hanh" in text or "bảo hành" in text)
        needs_ticket = any(keyword in text for keyword in ticket_keywords)
        self.trace.append({"step": "intent_detection", "user_input": user_input,
                           "needs_catalog": needs_catalog, "needs_ticket": needs_ticket})

        if not needs_catalog and not needs_ticket:
            answer = self._faq_answer(text)
            self.trace.append({"step": "final_answer", "observation": answer})
            return {"answer": answer, "trace": self.trace, "iterations": 1, "status": "completed"}

        actions = []
        if needs_catalog:
            actions.append(("catalog", self._catalog_arguments(text)))
        if needs_ticket:
            actions.append(("ticket", self._ticket_arguments(user_input)))

        observations = []
        for iteration, (action, arguments) in enumerate(actions, start=1):
            if iteration > self.max_iterations:
                return {"answer": "Loi: Vuot qua so buoc toi da.", "trace": self.trace,
                        "iterations": iteration - 1, "status": "max_iterations_reached"}
            observation = search_product_catalog(**arguments) if action == "catalog" else submit_support_ticket(**arguments)
            self.trace.append({"step": iteration, "action": action, "arguments": arguments, "observation": observation})
            observations.append((action, observation))

        answer = self._final_answer(observations)
        self.trace.append({"step": "final_answer", "observation": answer})
        return {"answer": answer, "trace": self.trace, "iterations": len(actions), "status": "completed"}

    @staticmethod
    def _catalog_arguments(text: str) -> Dict[str, Any]:
        category = "du_lich" if any(word in text for word in ("vinpearl", "du lich", "du lịch", "resort")) else "xe_dien"
        match = re.search(r"(?:duoi|dưới|toi da|tối đa)\s+(\d+(?:[.,]\d+)?)\s*(trieu|triệu|ty|tỷ|m|million)?", text)
        max_price = 999999999999
        if match:
            amount = float(match.group(1).replace(",", "."))
            unit = match.group(2) or ""
            multiplier = 1_000_000_000 if unit in ("ty", "tỷ") else 1_000_000 if unit in ("trieu", "triệu", "m", "million") else 1
            max_price = int(amount * multiplier)
        return {"category": category, "max_price": max_price}

    @staticmethod
    def _ticket_arguments(user_input: str) -> Dict[str, Any]:
        name_match = re.search(r"(?:toi ten|tôi tên|ten toi la|tên tôi là)\s+([^,;.]+)", user_input, re.IGNORECASE)
        customer_name = name_match.group(1).strip() if name_match else "Khach hang"
        priority = "high" if any(word in user_input.lower() for word in ("nghiem trong", "nghiêm trọng", "gap", "gấp", "khan cap", "khẩn cấp")) else "medium"
        return {"customer_name": customer_name, "issue_description": user_input, "priority": priority}

    @staticmethod
    def _faq_answer(text: str) -> str:
        if "bao hanh" in text or "bảo hành" in text:
            return "Chính sách bảo hành pin VinFast trong dữ liệu FAQ là 10 năm. Vui lòng liên hệ đại lý để xác nhận điều kiện áp dụng."
        return "Tôi có thể hỗ trợ tra cứu sản phẩm VinFast, Vinpearl hoặc tạo yêu cầu hỗ trợ."

    @staticmethod
    def _final_answer(observations: List[Any]) -> str:
        parts = []
        for action, observation in observations:
            if action == "catalog":
                if not observation or "error" in observation[0]:
                    parts.append("Rất tiếc, không tìm thấy sản phẩm phù hợp.")
                else:
                    products = "; ".join(f"{item['name']} ({item['price_vnd']:,} VND)" for item in observation)
                    parts.append(f"Sản phẩm phù hợp: {products}.")
            else:
                parts.append(f"Đã tạo ticket {observation['ticket_id']} cho {observation['customer_name']}, ưu tiên {observation['priority']}.")
        return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — Chạy thử nhanh
# ═══════════════════════════════════════════════════════════════════════════

def main():
    user_query = "Tôi muốn xem xe điện VinFast giá dưới 600 triệu."

    print("=== RUNNING CHATBOT BASELINE ===")
    chatbot = ChatbotBaseline()
    print(chatbot.query(user_query))

    print("\n=== RUNNING TOOL CALLING AGENT ===")
    agent = ToolCallingAgent(max_iterations=5)
    result = agent.run(user_query)
    print("Result:", result["answer"])
    print("Trace Log:", json.dumps(agent.trace, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
