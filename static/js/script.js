// JavaScript for chat interaction
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');

const loadingGifPath = 'static/icons/typing-gif.gif';
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg';

// Debounce function to limit the rate of function calls
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

// Function to automatically scroll to the latest message
const scrollToBottom = debounce(() => {
    chatWindow.scrollTop = chatWindow.scrollHeight;
}, 100);

// Function to format the message by converting URLs into clickable links
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });
}

// Function to create chat bubbles
function createChatBubble(message, sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    if (sender === 'kachifo') {
        const kachifoLogo = document.createElement('img');
        kachifoLogo.src = kachifoLogoPath;
        kachifoLogo.alt = 'Kachifo Logo';
        kachifoLogo.classList.add('kachifo-logo-small');
        bubble.appendChild(kachifoLogo);
    }

    const messageContent = document.createElement('div');
    messageContent.classList.add('message-content');

    if (isTyping) {
        const loadingGif = document.createElement('img');
        loadingGif.src = loadingGifPath;
        loadingGif.alt = 'Kachifo is typing...';
        loadingGif.classList.add('loading-gif');
        messageContent.appendChild(loadingGif);
    } else {
        messageContent.innerHTML = formatMessageWithLinks(message);
    }

    bubble.appendChild(messageContent);
    chatWindow.appendChild(bubble);
    scrollToBottom();
    return bubble;
}

// Function to handle sending a message
async function sendMessage(message) {
    if (!message) {
        message = userInput.value.trim();
    }
    if (message === '') return;

    console.log('Search initiated', { query: message, timestamp: new Date().toISOString() });
    createChatBubble(message, 'user');
    userInput.value = '';
    userInput.style.height = 'auto';
    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    const typingBubble = createChatBubble('', 'kachifo', true);

    try {
        const response = await fetch('/process-query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ q: message }),
            timeout: 30000 // 30 seconds timeout
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        typingBubble.remove();

        if (data.data && data.data.general_summary && data.data.dynamic_response && data.data.results) {
            const formattedResponse = formatResponse(data.data);
            createChatBubble(formattedResponse, 'kachifo');
        } else if (data.error) {
            createChatBubble(`Error: ${data.error}`, 'kachifo');
        } else {
            createChatBubble('Received an unexpected response format.', 'kachifo');
            console.error('Unexpected response format:', data);
        }
    } catch (error) {
        console.error('Error:', error);
        typingBubble.remove();
        createChatBubble('Something went wrong. Please try again.', 'kachifo');
    }
}

// Function to format the response in a more conversational manner
function formatResponse(data) {
    let response = `${data.general_summary} ${data.dynamic_response}\n\n`;
    response += "Here's what I found:\n\n";

    data.results.forEach((item, index) => {
        response += `<strong>${index + 1}. ${item.title}</strong>\n`;
        response += `${item.summary}\n`;
        if (item.url) {
            response += `<a href="${item.url}" target="_blank" rel="noopener noreferrer">Learn more</a>\n`;
        }
        response += '\n';
    });

    return response;
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Event listener for the send button
sendBtn.addEventListener('click', () => {
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

// Event listeners for suggestions
document.querySelectorAll('.suggestion').forEach(suggestion => {
    suggestion.addEventListener('click', () => {
        sendMessage(suggestion.textContent);
    });
});

// Event listener for the New Chat icon
newChatIcon.addEventListener('click', resetChat);

// Function to reset the chat
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    scrollToBottom();
}

// Initial scroll to bottom on page load
scrollToBottom();

// Error handling for unhandled promise rejections
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});