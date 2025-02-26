// JavaScript for chat interaction and handling API responses

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');
const loadingGifPath = '/static/icons/typing-gif.gif';
const kachifoLogoPath = '/static/logo/kachifo-logo-small.svg';

// Preloaded loading messages moved to the frontend
const loadingMessages = [
    "AI is fetching trends for you!",
    "Hold tight! We're gathering data...",
    "Did you know? Honey never spoils.",
    "Fun fact: Octopuses have three hearts.",
    "Did you know AI can predict trends 10x faster than humans?",
    "Tip: Try searching for trending news about technology."
];

// Helper function: Scroll to the latest message
const scrollToBottom = () => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
};

// Function to format message with embedded URLs
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">[link]</a>`;
    });
}

// Function to create a chat bubble element
function createChatBubble(sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    if (sender === 'kachifo') {
        const logoImg = document.createElement('img');
        logoImg.src = kachifoLogoPath;
        logoImg.alt = 'Kachifo Logo';
        logoImg.classList.add('kachifo-logo-small');
        bubble.appendChild(logoImg);
    }
    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');
    if (isTyping) {
        // Optionally show a static loading gif initially
        const loadingGif = document.createElement('img');
        loadingGif.src = loadingGifPath;
        loadingGif.alt = 'Loading...';
        loadingGif.classList.add('loading-gif');
        messageContent.appendChild(loadingGif);
    }
    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);
    scrollToBottom();
    return messageContent;
}

// Function to simulate streaming responses and display loading messages
function startStreaming(message, typingBubble) {
    // Start cycling through loading messages every 2 seconds
    let loadingInterval = setInterval(() => {
        const randomMessage = loadingMessages[Math.floor(Math.random() * loadingMessages.length)];
        typingBubble.innerHTML = `<p class="loading-message">${randomMessage}</p>`;
        scrollToBottom();
    }, 2000);

    // Fetch the final response from the backend
    fetch('/interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: message })
    })
    .then(response => response.json())
    .then(data => {
        clearInterval(loadingInterval);
        let displayText = "";
        // Determine response type based on API output
        if (data.response) {
            displayText = data.response;
        } else if (data.general_summary) {
            displayText = data.general_summary;
        }
        // Clear the typing indicator and start token-by-token animation
        typingBubble.innerHTML = "";
        const tokens = displayText.split(" ");
        let index = 0;
        const interval = setInterval(() => {
            if (index < tokens.length) {
                const span = document.createElement('span');
                span.textContent = tokens[index] + " ";
                span.style.opacity = '0';
                span.style.transition = 'opacity 0.5s ease-in';
                typingBubble.appendChild(span);
                setTimeout(() => {
                    span.style.opacity = '1';
                }, 10);
                index++;
                scrollToBottom();
            } else {
                clearInterval(interval);
            }
        }, 200); // Adjust timing as needed for smoothness
    })
    .catch(error => {
        clearInterval(loadingInterval);
        console.error("Error fetching response:", error);
        typingBubble.innerHTML = `<p class="error-message">Error processing response. Please try again.</p>`;
    });
}

// Function to send a message
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;
    // Display user's message
    createChatBubble('user').innerHTML = formatMessageWithLinks(message);
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');
    // Create a bubble for Kachifo's response with a typing indicator
    const typingBubble = createChatBubble('kachifo', true);
    // Start the simulated streaming (with loading messages)
    startStreaming(message, typingBubble);
}

// Function to reset the chat window
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    userInput.value = '';
    scrollToBottom();
    attachSuggestionListeners();
}

// Attach suggestion listeners dynamically
function attachSuggestionListeners() {
    const suggestionElements = document.querySelectorAll('.suggestion');
    suggestionElements.forEach(suggestion => {
        suggestion.addEventListener('click', handleSuggestionClick);
    });
}

// Handle suggestion click events
function handleSuggestionClick(event) {
    const suggestionText = event.target.textContent.trim();
    if (suggestionText) {
        sendMessage(suggestionText);
    }
}

// Event listeners and initialization
document.addEventListener('DOMContentLoaded', () => {
    attachSuggestionListeners();
});

sendBtn.addEventListener('click', (e) => {
    e.preventDefault();
    sendMessage();
});

userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && window.innerWidth >= 1024) {
        e.preventDefault();
        sendMessage();
    }
});

// Auto-resize input field with debounce
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

userInput.addEventListener('input', debounce(function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.value.trim() !== '') {
        initialView.classList.add('typing');
        suggestions.classList.add('typing');
    } else {
        initialView.classList.remove('typing');
        suggestions.classList.remove('typing');
    }
}, 100));

newChatIcon.addEventListener('click', (e) => {
    e.preventDefault();
    resetChat();
});

window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

window.onerror = function(message, source, lineno, colno, error) {
    console.error('Global error:', message, 'at', source, lineno, colno, error);
};