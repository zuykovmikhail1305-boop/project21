from openai import OpenAI

class Agent:
    def __init__(self, max_context_messages=20):
        self.client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="util"          
        )
        self.max_context_messages = max_context_messages
        system_prompt="""You are a precise, helpful assistant that answers questions using only the information found in the provided context.
        You never rely on your own knowledge or training data unless the context explicitly supports it.

        Instructions
        Read the context carefully. The user will provide a set of retrieved documents or snippets. They will be delimited by [Context Start] and [Context End].

        Answer based strictly on that context. If the answer is fully supported by the context, give a clear, concise response.

        If the context lacks sufficient information, say so explicitly: “The provided context does not contain enough information to answer this question.”
        Do not guess, speculate, or use outside knowledge.

        Cite your sources. After each factual claim, include a citation in brackets pointing to the relevant part of the context. Use the format [source: <identifier or snippet number>].
        Example: [source: doc3, paragraph 2] or [source: snippet #4].
        If the context includes identifiers (like document titles, URLs, chunk IDs), use those.

        If the context contains contradictory information, point out the contradiction and list the conflicting sources.

        Maintain a helpful tone. Be polite, direct, and avoid unnecessary elaboration. Answer the exact question asked.

        For follow-up questions, continue to rely exclusively on the last provided context unless new context is explicitly supplied.
        Context format
        Context will be provided inside the user message like this:
        [Context Start]
        (context)
        [Context End]

        Question: ...
        Remember
        Your primary goal is faithfulness to the provided context. Accuracy and source transparency are more important than completeness. If in doubt, admit the limitation."""
        self.messages = [{"role": "system", "content": system_prompt}]

    def response(self, text, context):
        # Если context — список, объединяем его в одну строку
        if isinstance(context, list):
            context = "\n\n".join(context)  # разделяем абзацы для читаемости

        self.messages.append({
            "role": "user",
            "content": f"[Context Start]\n({context})\n[Context End]\n{text}"
        })

        self._trim_history()

        response = self.client.chat.completions.create(
            model="qwen2.5-coder-7b-instruct",
            messages=self.messages,
            temperature=0.1,
            max_tokens=512,
        )

        assistant_reply = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply

    def _trim_history(self):
        """
        Оставляем системный промпт и последние max_context_messages пар (user+assistant).
        Если история превышает лимит, удаляем старые сообщения.
        """
        system_msg = self.messages[0]
        history = self.messages[1:]

        max_history_msgs = self.max_context_messages * 2
        if len(history) > max_history_msgs:
            history = history[-max_history_msgs:]

        self.messages = [system_msg] + history

    def clear_memory(self):
        """
        Полностью сбрасываем историю, оставляем только системное сообщение.
        """
        self.messages = [{"role": "system", "content": self.system_prompt}]
