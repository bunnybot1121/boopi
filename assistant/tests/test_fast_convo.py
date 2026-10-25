import re

def test_phrases():
    fast_convo = {
        "how are you": "I'm doing great! How can I help you today?",
        "how are you doing": "I'm doing awesome! All systems running smoothly. What's up?",
        "how are things": "Everything is running great! What can I do for you?",
        "how is it going": "It's going wonderful! Ready for action.",
        "hows it going": "It's going wonderful! Ready for action.",
        "whats up": "Hey! I'm here and ready to help.",
        "what is up": "Hey! I'm here and ready to help.",
        "whats going on": "Everything is running smoothly! Ready to help whenever you are.",
        "what is going on": "All systems are active and running smoothly! How can I help you?",
        "what are you doing": "I'm right here assisting you! Ready to chat, automate tasks, or drive our robots.",
        "what are you up to": "Just standing by and ready for your commands! What's on your mind?",
        "what are you working on": "I'm currently standing by and monitoring our system. What would you like to work on?",
        "what do you think": "I think everything is looking great! What would you like to do next?",
        "what are you thinking": "Just thinking about what we should build or explore next! What would you like to do?",
        "what are you thinking about": "Just thinking about what we should build or explore next! What would you like to do?",
        "who are you": "I'm Boopi, your AI companion and robotics assistant!",
        "what is your name": "My name is Boopi! I'm your AI companion and robotics assistant.",
        "whats your name": "My name is Boopi! I'm your AI companion and robotics assistant.",
        "what's your name": "My name is Boopi! I'm your AI companion and robotics assistant.",
        "tell me your name": "I'm Boopi! Your AI companion and robotics assistant.",
        "are you bupi": "Yes! I'm Boopi, also known as Bupi! Ready to help you.",
        "are you boopi": "Yes! I'm Boopi! Your energetic AI companion and robotics assistant.",
        "what can you do": "I can chat, automate your desktop, and command the physical BUPI robots! Just let me know what you need.",
        "can you hear me": "Yes, I can hear you loud and clear! How can I help you?",
        "can you hear me now": "Yes, I can hear you loud and clear! What's on your mind?",
        "can you hear": "Yes, I can hear you clearly! What do you need?",
        "are you listening": "Yes, I'm listening! What can I do for you?",
        "are you there": "I'm right here! Ready to help you.",
        "he is not responding": "I'm right here and listening! Sorry about that, I am completely ready for your instructions.",
        "he is not responding to me": "I'm right here and listening to you! Sorry about that, all systems are active and ready. What can I do for you?",
        "you are not responding": "I'm right here and listening! How can I help you?",
        "you are not listening": "I am listening! Please tell me what you need."
    }

    test_queries = [
        "What are you doing?",
        "What's going on, Boopi?",
        "Hey Boopi, what are you doing?",
        "What are you up to?",
        "What are you working on?",
        "What are you thinking?",
        "Boopi, what's going on?",
        "What is going on?",
        "Can you hear me?",
        "How are you doing?"
    ]

    for q in test_queries:
        clean_norm = re.sub(r"[^\w\s]", "", q).strip().lower()
        clean_sub = re.sub(r"^(?:(?:hey|hi|hello|yo|ok|okay|please|boopi|bupi)\s+)+", "", clean_norm).strip()
        clean_sub = re.sub(r"(?:\s+(?:boopi|bupi|please))+$", "", clean_sub).strip()
        
        match = fast_convo.get(clean_norm) or fast_convo.get(clean_sub)
        print(f"Query: '{q}' -> Matched: {bool(match)} -> '{match}'")
        assert match is not None, f"Failed to match query: '{q}'"

    print("\nAll fast_convo tests passed successfully!")

if __name__ == "__main__":
    test_phrases()
