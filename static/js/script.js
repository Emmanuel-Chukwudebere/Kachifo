// JavaScript for chat interaction and handling API responses

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

// Function to format the message by converting URLs into clickable 'Read more' links
function formatMessageWithLinks(message) {
    const urlRegex = /(https?:\/\/[^\s]+)/g;
    // Replace URLs with 'Read more' links
    return message.replace(urlRegex, (url) => {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">Read more</a>`;
    });
}

// Function to create chat bubbles with Kachifo logo and loading indicator
function createChatBubble(message, sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    if (sender === 'kachifo' && !isTyping) {
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

    const typingBubble = createChatBubble('', 'kachifo', true); // Show loading GIF

    // Sending a POST request for the user input
    try {
        const response = await fetch('/interact', {
            method: 'POST',  // Use POST for sending user input
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ input: message }),  // Send the user input as JSON
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // Start streaming responses
        startStreaming(message, typingBubble);
    } catch (error) {
        console.error('Error:', error);
        typingBubble.remove(); // Remove loading GIF on error
        createChatBubble("I'm sorry, but something went wrong on my end. Could we try that again?", 'kachifo');
    }
}

// Function to handle streaming responses
function startStreaming(message, typingBubble) {
    const eventSource = new EventSource(`/interact?input=${encodeURIComponent(message)}`);

    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.error) {
            createChatBubble(data.error, 'kachifo');
            typingBubble.remove(); // Remove loading GIF if there's an error
            eventSource.close();
        } else if (data.results) {
            // Remove loading GIF only when we receive the first data
            typingBubble.remove(); // Ensure typing bubble is removed
            // Combine results into a single message
            const combinedResponse = data.results.map(item => 
                `${item.title}: ${item.summary} <a href="${item.url}" target="_blank" rel="noopener noreferrer">Read more</a>`
            ).join('\n\n');
            createChatBubble(combinedResponse, 'kachifo'); // Display the streamed response
        } else {
            // This condition handles the loading messages sent from the server
            createChatBubble(data, 'kachifo'); // Display the loading message
        }
    };

    eventSource.onerror = function(error) {
        console.error("EventSource failed:", error);
        createChatBubble("I'm sorry, but something went wrong while fetching the data.", 'kachifo');
        typingBubble.remove(); // Ensure typing bubble is removed
        eventSource.close();
    };
}

// Function to reset the chat
function resetChat() {
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    scrollToBottom();
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Event listener for the send button
sendBtn.addEventListener('click', () => {
    // Track the button click event
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

// Event listeners for suggestions
document.querySelectorAll('.suggestion').forEach(suggestion => {
    suggestion.addEventListener('click', () => {
        sendMessage(suggestion.textContent);
    });
});

// Event listener for the New Chat icon
newChatIcon.addEventListener('click', resetChat);

// Initial scroll to bottom on page load
scrollToBottom();

// Error handling for unhandled promise rejections
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});