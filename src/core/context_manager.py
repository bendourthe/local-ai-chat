"""
Context window management for conversation handling.

Manages conversation context within token limits using truncation and summarization.
Implements sliding window and intelligent message selection strategies.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import re
from typing import List, Dict, Tuple, Optional
from .tokens import estimate_tokens


class ContextManager:
    """Manage conversation context within token limits."""
    
    def __init__(self, max_tokens: int = 4096, reserve_tokens: int = 512):
        """Initialize context manager with token limits."""
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens  # Reserve for response
        self.available_tokens = max_tokens - reserve_tokens
        
    def truncate_messages(self, messages: List[Dict]) -> List[Dict]:
        """Truncate messages to fit within context window."""
        if not messages:
            return messages
            
        # Always keep system messages and the last user message
        system_messages = [m for m in messages if m.get('role') == 'system']
        other_messages = [m for m in messages if m.get('role') != 'system']
        
        if not other_messages:
            return system_messages
            
        # Keep the last user message (current prompt)
        last_message = other_messages[-1] if other_messages else None
        conversation_messages = other_messages[:-1] if len(other_messages) > 1 else []
        
        # Calculate token usage for required messages
        system_tokens = sum(estimate_tokens(m.get('content', '')) for m in system_messages)
        last_message_tokens = estimate_tokens(last_message.get('content', '')) if last_message else 0
        
        required_tokens = system_tokens + last_message_tokens
        available_for_history = self.available_tokens - required_tokens
        
        if available_for_history <= 0:
            # Not enough space for history, return only required messages
            result = system_messages[:]
            if last_message:
                result.append(last_message)
            return result
        
        # Select conversation history using sliding window
        selected_history = self._select_conversation_history(
            conversation_messages, available_for_history
        )
        
        # Combine all selected messages
        result = system_messages[:]
        result.extend(selected_history)
        if last_message:
            result.append(last_message)
            
        return result
    
    def _select_conversation_history(self, messages: List[Dict], token_budget: int) -> List[Dict]:
        """Select conversation history messages within token budget."""
        if not messages:
            return []
            
        # Start from the most recent messages and work backwards
        selected = []
        current_tokens = 0
        
        for message in reversed(messages):
            content = message.get('content', '')
            msg_tokens = estimate_tokens(content)
            
            if current_tokens + msg_tokens <= token_budget:
                selected.insert(0, message)  # Insert at beginning to maintain order
                current_tokens += msg_tokens
            else:
                # Try to include a truncated version of this message if it's important
                if self._is_important_message(message) and len(selected) < 2:
                    remaining_budget = token_budget - current_tokens
                    if remaining_budget > 50:  # Only if we have reasonable space
                        truncated_content = self._truncate_content(content, remaining_budget)
                        if truncated_content:
                            truncated_msg = message.copy()
                            truncated_msg['content'] = truncated_content
                            selected.insert(0, truncated_msg)
                            break
                else:
                    break
                    
        return selected
    
    def _is_important_message(self, message: Dict) -> bool:
        """Determine if a message is important to preserve."""
        content = message.get('content', '').lower()
        role = message.get('role', '')
        
        # Consider user questions and assistant responses with key information
        if role == 'user':
            # Questions and commands are usually important
            return any(marker in content for marker in [
                '?', 'how', 'what', 'why', 'when', 'where', 'can you', 'please'
            ])
        elif role == 'assistant':
            # Responses with structured information, code, or explanations
            return any(marker in content for marker in [
                '```', 'def ', 'class ', 'import ', 'function', 'method',
                '1.', '2.', '- ', '* ', 'steps:', 'example:'
            ])
            
        return False
    
    def _truncate_content(self, content: str, max_tokens: int) -> str:
        """Truncate content to fit within token limit while preserving meaning."""
        if estimate_tokens(content) <= max_tokens:
            return content
            
        # Try to truncate at sentence boundaries
        sentences = re.split(r'[.!?]+', content)
        if len(sentences) > 1:
            truncated = ""
            for sentence in sentences:
                test_content = truncated + sentence + "."
                if estimate_tokens(test_content) <= max_tokens:
                    truncated = test_content
                else:
                    break
            
            if truncated:
                return truncated + "..."
        
        # Fallback: truncate by approximate character count
        # Rough estimate: 1 token ≈ 4 characters
        max_chars = max_tokens * 3
        if len(content) > max_chars:
            return content[:max_chars] + "..."
            
        return content
    
    def should_summarize(self, messages: List[Dict]) -> bool:
        """Check if messages should be summarized."""
        total_tokens = self.estimate_total_tokens(messages)
        return total_tokens > self.max_tokens * 0.7
    
    def estimate_total_tokens(self, messages: List[Dict]) -> int:
        """Estimate total tokens for a list of messages."""
        return sum(estimate_tokens(m.get('content', '')) for m in messages)
    
    def summarize_context(self, messages: List[Dict]) -> str:
        """Create a summary of older messages."""
        if not messages:
            return ""
            
        # Group messages by conversation turns (user-assistant pairs)
        turns = []
        current_turn = []
        
        for message in messages:
            role = message.get('role', '')
            if role == 'system':
                continue  # Skip system messages for summarization
                
            current_turn.append(message)
            
            # Complete turn when we have both user and assistant messages
            if len(current_turn) >= 2 or role == 'assistant':
                turns.append(current_turn[:])
                current_turn = []
        
        if not turns:
            return ""
        
        # Summarize key points from the conversation
        summary_points = []
        
        for i, turn in enumerate(turns):
            user_msg = next((m for m in turn if m.get('role') == 'user'), None)
            assistant_msg = next((m for m in turn if m.get('role') == 'assistant'), None)
            
            if user_msg:
                user_content = user_msg.get('content', '')
                if len(user_content) > 50:  # Only summarize substantial messages
                    # Extract key topics or questions
                    topic = self._extract_topic(user_content)
                    if topic:
                        summary_points.append(f"User asked about {topic}")
            
            if assistant_msg:
                assistant_content = assistant_msg.get('content', '')
                if len(assistant_content) > 100:  # Only summarize substantial responses
                    # Extract key information provided
                    key_info = self._extract_key_info(assistant_content)
                    if key_info:
                        summary_points.append(f"Assistant explained {key_info}")
        
        if summary_points:
            return "Previous conversation summary:\n" + "\n".join(f"- {point}" for point in summary_points[:5])
        
        return f"Previous conversation involved {len(turns)} exchanges between user and assistant."
    
    def _extract_topic(self, content: str) -> str:
        """Extract main topic from user message."""
        content_lower = content.lower()
        
        # Look for common question patterns
        question_patterns = [
            r'how (?:do|can|to) (.*?)[\?\.]',
            r'what (?:is|are) (.*?)[\?\.]',
            r'why (?:does|is|are) (.*?)[\?\.]',
            r'explain (.*?)[\?\.]',
            r'tell me about (.*?)[\?\.]'
        ]
        
        for pattern in question_patterns:
            match = re.search(pattern, content_lower)
            if match:
                topic = match.group(1).strip()
                if len(topic) < 50:  # Reasonable topic length
                    return topic
        
        # Fallback: extract first few meaningful words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', content)
        if words:
            return ' '.join(words[:3])
            
        return "general topic"
    
    def _extract_key_info(self, content: str) -> str:
        """Extract key information from assistant response."""
        # Look for structured information
        if '```' in content:
            return "code examples"
        elif any(marker in content for marker in ['1.', '2.', '- ', '* ']):
            return "step-by-step information"
        elif len(content) > 500:
            return "detailed information"
        else:
            return "information"
    
    def get_context_window_usage(self, messages: List[Dict]) -> Tuple[int, int, float]:
        """Get context window usage statistics."""
        used_tokens = self.estimate_total_tokens(messages)
        usage_percent = (used_tokens / self.max_tokens) * 100.0
        return used_tokens, self.max_tokens, usage_percent
    
    def set_max_tokens(self, max_tokens: int) -> None:
        """Update maximum token limit."""
        self.max_tokens = max(1024, max_tokens)  # Minimum 1024 tokens
        self.available_tokens = self.max_tokens - self.reserve_tokens
    
    def set_reserve_tokens(self, reserve_tokens: int) -> None:
        """Update reserved tokens for response generation."""
        self.reserve_tokens = max(256, reserve_tokens)  # Minimum 256 tokens reserved
        self.available_tokens = self.max_tokens - self.reserve_tokens
