// JavaScript for chat interaction and handling API responses

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.getElementById('new-chat-icon'); // Ensure this ID exists in your HTML
const loadingGifPath = '/static/icons/typing-gif.gif';
const kachifoLogoPath = '/static/logo/kachifo-logo-small.svg';

// Expanded set of loading messages
const loadingMessages = [
    "AI is fetching trends for you!",
    "Hold tight! We're gathering data...",
    "Did you know? Honey never spoils.",
    "Fun fact: Octopuses have three hearts.",
    "AI is crunching the latest data—please wait.",
    "Stay tuned! We're compiling the top trends.",
    "Pro tip: Great insights are on the way.",
    "Your trends are being curated in real-time."
];

// Helper function: Scroll to the latest message
const scrollToBottom = () => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
};

// Helper function to animate text token-by-token
function animateText(element, text, tokenInterval = 200) {
    element.innerHTML = "";
    const tokens = text.split(" ");
    let index = 0;
    const interval = setInterval(() => {
        if (index < tokens.length) {
            const span = document.createElement('span');
            span.textContent = tokens[index] + " ";
            span.style.opacity = '0';
            span.style.transition = 'opacity 0.5s ease-in';
            element.appendChild(span);
            setTimeout(() => {
                span.style.opacity = '1';
            }, 10);
            index++;
            scrollToBottom();
        } else {
            clearInterval(interval);
        }
    }, tokenInterval);
}

// Function to format messages by embedding URLs as clickable links
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">[link]</a>`;
    });
}

// Create a chat bubble element for user or Kachifo
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

// Simulate streaming responses with loading messages then animate final response
function startStreaming(message, typingBubble) {
    let loadingInterval = setInterval(() => {
        const randomMessage = loadingMessages[Math.floor(Math.random() * loadingMessages.length)];
        animateText(typingBubble, randomMessage, 100);
    }, 4000);

    fetch('/interact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: message })
    })
    .then(response => response.json())
    .then(data => {
        clearInterval(loadingInterval);
        let displayText = "";
        if (data.response) {
            displayText = data.response;
        } else if (data.general_summary) {
            displayText = data.general_summary;
        }
        typingBubble.innerHTML = "";
        animateText(typingBubble, displayText, 200);
    })
    .catch(error => {
        clearInterval(loadingInterval);
        console.error("Error fetching response:", error);
        typingBubble.innerHTML = `<p class="error-message">Error processing response. Please try again.</p>`;
    });
}

// Send a message from the user
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;
    createChatBubble('user').innerHTML = formatMessageWithLinks(message);
    userInput.value = '';
    if (userInput) {
        userInput.style.maxHeight = "none";
        userInput.style.height = 'auto';
        userInput.style.height = userInput.scrollHeight + 'px';
    }
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');
    const typingBubble = createChatBubble('kachifo', true);
    startStreaming(message, typingBubble);
}

// Reset the chat window for a new conversation
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    if (userInput) {
        userInput.value = '';
        userInput.style.height = 'auto';
    }
    scrollToBottom();
    attachSuggestionListeners();
}

// Attach listeners to suggestion elements
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

// Debounce for auto-resizing input field
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

userInput && userInput.addEventListener('input', debounce(function() {
    if (this) {
        this.style.maxHeight = "none";
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
    }
    if (this.value.trim() !== '') {
        initialView.classList.add('typing');
        suggestions.classList.add('typing');
    } else {
        initialView.classList.remove('typing');
        suggestions.classList.remove('typing');
    }
}, 100));

// Attach reset chat listener only if the element exists
if (newChatIcon) {
    newChatIcon.addEventListener('click', (e) => {
        e.preventDefault();
        resetChat();
    });
} else {
    console.warn("newChatIcon element not found.");
}

window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

window.onerror = function(message, source, lineno, colno, error) {
    console.error('Global error:', message, 'at', source, lineno, colno, error);
};