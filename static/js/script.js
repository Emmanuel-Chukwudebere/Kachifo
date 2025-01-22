// Enhanced frontend JavaScript with streaming handled client-side
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');

// Configuration
const CONFIG = {
    ANIMATION_DURATION: 300,
    TYPING_DELAY: 50,
    MAX_RETRIES: 3,
    LOADING_MESSAGES: [
        "AI is fetching trends for you!",
        "Hold tight! We're gathering data...",
        "Did you know: The term 'trending' was popularized by social media?",
        "Did you know? Honey never spoils.",
        "Fact: Bananas are berries, but strawberries aren't!",
        "Fun fact: Octopuses have three hearts.",
        "A group of flamingos is called a 'flamboyance.'",
        "Cats have fewer toes on their back paws.",
        "Sharks existed before trees.",
        "A snail can sleep for three years.",
        "Wombat poop is cube-shaped.",
        "You can't hum while holding your nose closed.",
        "Bees can recognize human faces.",
        "Did you know AI can predict trends 10x faster than humans?",
        "Tip: Try searching for trending news about technology.",
        "Here's a fun fact: The first tweet was posted in 2006.",
        "Hold tight! We're fetching the latest news for you!",
        "Fun fact: Over 3.6 billion people use social media worldwide.",
        "Tip: Ask about the latest trends in your favorite topics!",
        "The word 'hashtag' was first used in 2007.",
        "Google processes over 3.5 billion searches per day."
    ]
};

// Message streaming class
class MessageStreamer {
    constructor(message, typingBubble) {
        this.message = message;
        this.typingBubble = typingBubble;
        this.loadingInterval = null;
        this.currentLoadingIndex = 0;
    }

    // Start showing loading messages while waiting for response
    startLoadingMessages() {
        this.loadingInterval = setInterval(() => {
            const loadingMessage = CONFIG.LOADING_MESSAGES[this.currentLoadingIndex];
            this.updateTypingBubble(loadingMessage);
            this.currentLoadingIndex = (this.currentLoadingIndex + 1) % CONFIG.LOADING_MESSAGES.length;
        }, 3000);
    }

    // Stop loading messages
    stopLoadingMessages() {
        if (this.loadingInterval) {
            clearInterval(this.loadingInterval);
            this.loadingInterval = null;
        }
    }

    // Animated update of typing bubble
    updateTypingBubble(content) {
        const currentContent = this.typingBubble.innerHTML;
        this.typingBubble.style.opacity = '0';
        
        setTimeout(() => {
            this.typingBubble.innerHTML = content;
            this.typingBubble.style.opacity = '1';
        }, CONFIG.ANIMATION_DURATION / 2);
    }

    // Stream the actual response
    async streamResponse(response) {
        this.stopLoadingMessages();
        
        if (response.type === 'conversation') {
            await this.streamText(response.response);
        } else if (response.type === 'query') {
            await this.streamResults(response.results);
        }
    }

    // Stream text character by character
    async streamText(text) {
        let currentText = '';
        for (let char of text) {
            currentText += char;
            this.updateTypingBubble(currentText);
            await new Promise(resolve => setTimeout(resolve, CONFIG.TYPING_DELAY));
        }
    }

    // Stream search results with animation
    async streamResults(results) {
        let html = '';
        for (const result of results) {
            const resultHTML = `
                <div class="result-item" style="opacity: 0; transform: translateY(20px);">
                    <h3>${result.title}</h3>
                    <p>${result.summary}</p>
                    <a href="${result.url}" target="_blank" rel="noopener noreferrer">[""]</a>
                </div>
            `;
            html += resultHTML;
            this.updateTypingBubble(html);
            
            // Animate each result item
            const items = this.typingBubble.querySelectorAll('.result-item');
            const lastItem = items[items.length - 1];
            
            setTimeout(() => {
                lastItem.style.opacity = '1';
                lastItem.style.transform = 'translateY(0)';
            }, 10);
            
            await new Promise(resolve => setTimeout(resolve, 300));
        }
    }

    // Error handling with animation
    handleError(error) {
        this.stopLoadingMessages();
        this.updateTypingBubble(`
            <div class="error-message" style="opacity: 0; transform: translateY(20px)">
                ${error.message || 'An error occurred. Please try again.'}
            </div>
        `);
        
        setTimeout(() => {
            const errorMessage = this.typingBubble.querySelector('.error-message');
            errorMessage.style.opacity = '1';
            errorMessage.style.transform = 'translateY(0)';
        }, 10);
    }
}

// Main message handling function
async function sendMessage(message = '') {
    const messageText = message || userInput.value.trim();
    if (!messageText) return;

    // Create chat bubbles
    const userBubble = createChatBubble('user');
    userBubble.innerHTML = messageText;
    
    const typingBubble = createChatBubble('kachifo');
    const streamer = new MessageStreamer(messageText, typingBubble);
    
    // Clear input and update UI
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    try {
        // Start loading animation
        streamer.startLoadingMessages();

        // Fetch response from backend
        const response = await fetch('/interact', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ input: messageText }),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        await streamer.streamResponse(data);

    } catch (error) {
        console.error('Error:', error);
        streamer.handleError(error);
    }
}

// Helper functions
function createChatBubble(sender) {
    const bubble = document.createElement('div');
    bubble.classList.add(`${sender}-message`);
    bubble.style.opacity = '0';
    bubble.style.transform = 'translateY(20px)';
    
    const content = document.createElement('div');
    content.classList.add('message-content');
    bubble.appendChild(content);
    
    chatWindow.appendChild(bubble);
    
    // Trigger animation
    setTimeout(() => {
        bubble.style.opacity = '1';
        bubble.style.transform = 'translateY(0)';
    }, 10);
    
    scrollToBottom();
    return content;
}

function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Attach event listeners for suggestions
    document.querySelectorAll('.suggestion').forEach(suggestion => {
        suggestion.addEventListener('click', (e) => {
            const text = e.target.textContent.trim();
            if (text) {
                sendMessage(text);
            }
        });
    });

    // Input handling
    userInput.addEventListener('input', debounce(function() {
        this.style.height = 'auto';
        this.style.height = `${this.scrollHeight}px`;
        
        if (this.value.trim()) {
            initialView.classList.add('typing');
            suggestions.classList.add('typing');
        } else {
            initialView.classList.remove('typing');
            suggestions.classList.remove('typing');
        }
    }, 100));

    // Send message handlers
    sendBtn.addEventListener('click', (e) => {
        e.preventDefault();
        sendMessage();
    });

    // Handle Enter key for desktop
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && window.innerWidth >= 1024) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Reset chat
    newChatIcon.addEventListener('click', () => {
        resetChat();
    });
});

// Utility functions
const debounce = (func, wait) => {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

function resetChat() {
    // Animate chat window fade out
    chatWindow.style.opacity = '0';
    
    setTimeout(() => {
        chatWindow.innerHTML = '';
        chatWindow.style.opacity = '1';
        initialView.classList.remove('hidden');
        suggestions.classList.remove('hidden');
        chatWindow.classList.remove('active');
        userInput.value = '';
    }, CONFIG.ANIMATION_DURATION);
}

// Error handling
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

window.onerror = function(message, source, lineno, colno, error) {
    console.error('Global error:', {
        message,
        source,
        lineno,
        colno,
        error
    });
};

// Add CSS for animations
const style = document.createElement('style');
style.textContent = `
    .message-content {
        transition: opacity ${CONFIG.ANIMATION_DURATION}ms ease-in-out,
                    transform ${CONFIG.ANIMATION_DURATION}ms ease-in-out;
    }
    
    .result-item {
        transition: opacity ${CONFIG.ANIMATION_DURATION}ms ease-in-out,
                    transform ${CONFIG.ANIMATION_DURATION}ms ease-in-out;
    }
    
    .chat-window {
        transition: opacity ${CONFIG.ANIMATION_DURATION}ms ease-in-out;
    }
    
    .error-message {
        transition: opacity ${CONFIG.ANIMATION_DURATION}ms ease-in-out,
                    transform ${CONFIG.ANIMATION_DURATION}ms ease-in-out;
        color: #ff4444;
        padding: 10px;
        border-radius: 5px;
        background-color: rgba(255, 68, 68, 0.1);
    }
`;
document.head.appendChild(style);