"""
Enhanced token tracking system for local AI inference integration.

Provides accurate token counting by hooking into the Microsoft Local AI foundry
tokenization process and capturing both input and output tokens including reasoning.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import re
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from .tokens import estimate_tokens


@dataclass
class TokenMetrics:
    """Token metrics for a single inference operation."""
    input_tokens: int
    output_tokens: int 
    reasoning_tokens: int
    total_tokens: int
    model_name: Optional[str] = None
    
    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens + self.reasoning_tokens


class TokenTracker:
    """
    Track token usage for local AI inference operations.
    
    Hooks into the Microsoft Local AI foundry CLI process to capture
    accurate token counts including reasoning/chain-of-thought tokens.
    """
    
    def __init__(self):
        """Initialize token tracker without side effects."""
        self._chat_tokens: Dict[str, List[TokenMetrics]] = {}
        self._pending_requests: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[str, TokenMetrics], None]] = []
        
    def register_callback(self, callback: Callable[[str, TokenMetrics], None]) -> None:
        """Register callback for token count updates."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
                
    def unregister_callback(self, callback: Callable[[str, TokenMetrics], None]) -> None:
        """Unregister token count update callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def start_request(self, chat_id: str, user_input: str, model_name: Optional[str] = None) -> str:
        """
        Start tracking a new inference request.
        
        Parameters:
            - chat_id (str): Chat identifier
            - user_input (str): User input text
            - model_name (str): Model name being used
            
        Returns:
            - str: Request ID for this tracking session
        """
        request_id = f"{chat_id}_{threading.get_ident()}_{id(user_input)}"
        
        # Estimate input tokens (will be replaced with actual if available)
        input_tokens = self._estimate_input_tokens(user_input, chat_id)
        
        with self._lock:
            self._pending_requests[request_id] = {
                'chat_id': chat_id,
                'user_input': user_input,
                'model_name': model_name,
                'input_tokens': input_tokens,
                'start_time': threading.get_ident()
            }
            
        return request_id
    
    def process_raw_output(self, request_id: str, raw_line: str) -> None:
        """
        Process raw CLI output line to extract token information.
        
        This method hooks into the foundry CLI output stream to capture
        token metrics that may be embedded in the response.
        """
        if request_id not in self._pending_requests:
            return
            
        # Look for token patterns in foundry CLI output
        # Common patterns from local inference engines:
        patterns = [
            r"input.*?(\d+).*?tokens?",
            r"output.*?(\d+).*?tokens?", 
            r"reasoning.*?(\d+).*?tokens?",
            r"generated.*?(\d+).*?tokens?",
            r"processed.*?(\d+).*?tokens?",
            r"total.*?(\d+).*?tokens?",
        ]
        
        line_lower = raw_line.lower()
        
        with self._lock:
            req = self._pending_requests.get(request_id)
            if not req:
                return
                
            # Extract token counts from CLI output if present
            for pattern in patterns:
                match = re.search(pattern, line_lower)
                if match:
                    token_count = int(match.group(1))
                    if "input" in line_lower or "processed" in line_lower:
                        req['actual_input_tokens'] = token_count
                    elif "output" in line_lower or "generated" in line_lower:
                        req['output_tokens'] = token_count
                    elif "reasoning" in line_lower:
                        req['reasoning_tokens'] = token_count
                    elif "total" in line_lower:
                        req['total_tokens'] = token_count
    
    def complete_request(self, request_id: str, assistant_output: str) -> Optional[TokenMetrics]:
        """
        Complete request tracking and return final token metrics.
        
        Parameters:
            - request_id (str): Request ID from start_request
            - assistant_output (str): Final assistant response text
            
        Returns:
            - TokenMetrics: Final token counts for this inference
        """
        with self._lock:
            req = self._pending_requests.pop(request_id, None)
            if not req:
                return None
                
            chat_id = req['chat_id']
            
            # Use actual token counts if available, otherwise estimate
            input_tokens = req.get('actual_input_tokens', req['input_tokens'])
            output_tokens = req.get('output_tokens', self._estimate_output_tokens(assistant_output))
            reasoning_tokens = req.get('reasoning_tokens', self._estimate_reasoning_tokens(assistant_output))
            total_tokens = req.get('total_tokens', input_tokens + output_tokens + reasoning_tokens)
            
            metrics = TokenMetrics(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                total_tokens=total_tokens,
                model_name=req.get('model_name')
            )
            
            # Store metrics for this chat
            if chat_id not in self._chat_tokens:
                self._chat_tokens[chat_id] = []
            self._chat_tokens[chat_id].append(metrics)
            
            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(chat_id, metrics)
                except Exception:
                    pass
                    
            return metrics
    
    def get_chat_total_tokens(self, chat_id: str) -> int:
        """Return total tokens used in a chat session."""
        with self._lock:
            if chat_id not in self._chat_tokens:
                return 0
            return sum(m.total_tokens for m in self._chat_tokens[chat_id])
    
    def get_chat_metrics(self, chat_id: str) -> List[TokenMetrics]:
        """Return all token metrics for a chat session."""
        with self._lock:
            return self._chat_tokens.get(chat_id, []).copy()
    
    def clear_chat(self, chat_id: str) -> None:
        """Clear token tracking data for a specific chat."""
        with self._lock:
            self._chat_tokens.pop(chat_id, None)
            # Remove any pending requests for this chat
            to_remove = [rid for rid, req in self._pending_requests.items() 
                        if req.get('chat_id') == chat_id]
            for rid in to_remove:
                self._pending_requests.pop(rid, None)
    
    def clear_all(self) -> None:
        """Clear all token tracking data."""
        with self._lock:
            self._chat_tokens.clear()
            self._pending_requests.clear()
    
    def get_all_chat_tokens(self) -> Dict[str, int]:
        """Return total tokens for all tracked chats."""
        with self._lock:
            return {cid: sum(m.total_tokens for m in metrics) 
                   for cid, metrics in self._chat_tokens.items()}
    
    def _estimate_input_tokens(self, user_input: str, chat_id: str) -> int:
        """
        Estimate input tokens including conversation context.
        
        For local inference, input tokens include:
        - System prompts
        - Conversation history 
        - Current user input
        - Any preprocessing overhead
        """
        base_tokens = estimate_tokens(user_input)
        
        # Add overhead for system prompts and context (typical 50-200 tokens)
        system_overhead = 100
        
        # Add tokens for conversation history
        context_tokens = 0
        with self._lock:
            if chat_id in self._chat_tokens:
                # Approximate context from previous messages
                context_tokens = min(2048, sum(m.input_tokens + m.output_tokens 
                                             for m in self._chat_tokens[chat_id][-10:]))  # Last 10 exchanges
        
        return base_tokens + system_overhead + int(context_tokens * 0.1)  # 10% of context carried forward
    
    def _estimate_output_tokens(self, assistant_output: str) -> int:
        """Estimate visible output tokens."""
        return estimate_tokens(assistant_output)
    
    def _estimate_reasoning_tokens(self, assistant_output: str) -> int:
        """
        Estimate reasoning/chain-of-thought tokens.
        
        Local models often generate internal reasoning tokens that aren't
        displayed in the final response. Estimate based on output complexity.
        """
        output_tokens = estimate_tokens(assistant_output)
        
        # Heuristic: reasoning tokens are typically 20-50% of output for complex responses
        # Simple responses have minimal reasoning overhead
        if output_tokens < 50:
            return int(output_tokens * 0.1)  # 10% for simple responses
        elif output_tokens < 200:
            return int(output_tokens * 0.25)  # 25% for medium responses  
        else:
            return int(output_tokens * 0.4)   # 40% for complex responses


# Global token tracker instance
_token_tracker = TokenTracker()


def get_token_tracker() -> TokenTracker:
    """Get the global token tracker instance."""
    return _token_tracker
