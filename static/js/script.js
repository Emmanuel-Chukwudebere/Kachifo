// JavaScript for chat interaction and handling API responses

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');

const loadingGifPath = 'static/icons/typing-gif.gif';
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg';

// Helper function: Scroll to the latest message
const scrollToBottom = () => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
};

// Function to format message with URLs embedded in [""] instead of "Read more"
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">[""]</a>`;
    });
}

// Function to create a single, updatable chat bubble
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

// Function to handle streaming responses
function startStreaming(message, typingBubble) {
    const eventSource = new EventSource(`/interact?input=${encodeURIComponent(message)}`);

    let isFirstMessage = true;
    eventSource.onmessage = function (event) {
        const data = JSON.parse(event.data);
        if (data.error) {
            typingBubble.innerHTML = `<p class="error-message">${data.error}</p>`;
            eventSource.close();
        } else if (data.results) {
            const combinedResponse = data.results.map(item => `
                <div class="result-item">
                    <h3>${item.title}</h3>
                    <p>${item.summary}</p>
                    <a href="${item.url}" target="_blank" rel="noopener noreferrer">[""]</a>
                </div>
            `).join('');

            typingBubble.innerHTML = combinedResponse;
            eventSource.close();
        } else {
            if (isFirstMessage) {
                typingBubble.innerHTML = '';
                isFirstMessage = false;
            }

            const messageElement = document.createElement('p');
            messageElement.textContent = data;
            messageElement.style.opacity = '0';
            typingBubble.appendChild(messageElement);

            setTimeout(() => {
                messageElement.style.transition = 'opacity 0.5s ease-in';
                messageElement.style.opacity = '1';
            }, 10);

            if (typingBubble.childNodes.length > 1) {
                const oldMessage = typingBubble.childNodes[0];
                oldMessage.style.transition = 'opacity 0.5s ease-out';
                oldMessage.style.opacity = '0';
                setTimeout(() => oldMessage.remove(), 500);
            }
        }

        scrollToBottom();
    };

    eventSource.onerror = function (error) {
        console.error('EventSource failed:', error);
        typingBubble.innerHTML = `<p class="error-message">I'm sorry, something went wrong while fetching the data.</p>`;
        eventSource.close();
    };
}

// Function to handle sending a message
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }

    if (message === '') return;

    createChatBubble('user').innerHTML = formatMessageWithLinks(message);
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    const typingBubble = createChatBubble('kachifo', true);

    try {
        const response = await fetch('/interact', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ input: message }),
        });

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        
        startStreaming(message, typingBubble);
    } catch (error) {
        console.error('Error:', error);
        typingBubble.innerHTML = `<p class="error-message">I'm sorry, something went wrong. Please try again.</p>`;
    }
}

// Function to reset the chat
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    scrollToBottom();
    attachSuggestionListeners();  // Reattach listeners after reset
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Attach event listeners for suggestions dynamically
function attachSuggestionListeners() {
    document.querySelectorAll('.suggestion').forEach(suggestion => {
        suggestion.addEventListener('click', () => {
            sendMessage(suggestion.textContent);
        });
    });
}

// Event listener for the send button
sendBtn.addEventListener('click', () => {
    gtag('event', 'click', {
        'event_category': 'Button',
        'event_label': 'Send Message',
        'value': 1
    });
    sendMessage();
});

// Event listener for pressing "Enter" key in the input field (only for desktop)
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && isDesktop()) {
        e.preventDefault();
        sendMessage();
    }
});

// Auto-resize input field and handle typing state
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

// Event listener for the New Chat icon
newChatIcon.addEventListener('click', resetChat);

// Reattach suggestion event listeners on page load
document.addEventListener('DOMContentLoaded', () => {
    attachSuggestionListeners();
});

// Ensure listeners for dynamic suggestions are re-attached after DOM updates
const observer = new MutationObserver(() => {
    attachSuggestionListeners();
});

// Observe changes in the suggestions container
observer.observe(suggestions, { childList: true });

// Initial scroll to bottom on page load
scrollToBottom();

// Error handling for unhandled promise rejections
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});