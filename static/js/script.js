// JavaScript for chat interaction and handling API responses

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');

const loadingGifPath = '/static/icons/typing-gif.gif';
const kachifoLogoPath = '/static/logo/kachifo-logo-small.svg';

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
    console.log("Starting to stream for message:", message);
    const eventSource = new EventSource(`/interact?input=${encodeURIComponent(message)}`);

    eventSource.onopen = function(event) {
        console.log("EventSource connection opened");
    };

    let isFirstMessage = true;
    eventSource.onmessage = function (event) {
        console.log("Received event data:", event.data);
        try {
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
        } catch (error) {
            console.error('Error parsing event data:', error);
            typingBubble.innerHTML = `<p class="error-message">Error processing response. Please try again.</p>`;
            eventSource.close();
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
    console.log("Sending message:", message);
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

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        startStreaming(message, typingBubble);
    } catch (error) {
        console.error('Error:', error);
        typingBubble.innerHTML = `<p class="error-message">I'm sorry, something went wrong. Please try again.</p>`;
    }
}

// Function to reset the chat
function resetChat() {
    console.log("Resetting chat");
    chatWindow.innerHTML = '';
    initialView.classList.remove('hidden');
    suggestions.classList.remove('hidden');
    chatWindow.classList.remove('active');
    userInput.value = '';  // Clear input after reset
    scrollToBottom();
    attachSuggestionListeners();  // Reattach listeners after reset
}

// Function to check if the user is on a desktop
function isDesktop() {
    return window.innerWidth >= 1024;
}

// Function to attach event listeners for suggestions dynamically
function attachSuggestionListeners() {
    console.log("Attaching suggestion listeners");
    const suggestionElements = document.querySelectorAll('.suggestion');
    suggestionElements.forEach(suggestion => {
        suggestion.addEventListener('click', handleSuggestionClick);
    });
}

// Function to handle suggestion click
function handleSuggestionClick(event) {
    console.log("Suggestion clicked:", event.target.textContent.trim());
    const suggestionText = event.target.textContent.trim();
    if (suggestionText) {
        sendMessage(suggestionText);
    }
}

// Attach event listeners on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM fully loaded");
    attachSuggestionListeners();
});

// Event listener for the send button
sendBtn.addEventListener('click', (e) => {
    e.preventDefault();  // Prevent default form submission
    console.log("Send button clicked!");  // Check if the button click is registered
    sendMessage();  // Call your sendMessage function
});


// Event listener for pressing "Enter" key in the input field (only for desktop)
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && isDesktop()) {
        console.log("Enter key pressed");
        e.preventDefault();  // Prevent default Enter behavior (newline)
        sendMessage();       // Send the message instead
    }
});

// Debounce function
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
newChatIcon.addEventListener('click', (e) => {
    e.preventDefault(); // Prevent any default action
    console.log("Reset chat button clicked");
    resetChat();
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

// Log any global errors
window.onerror = function(message, source, lineno, colno, error) {
    console.error('Global error:', message, 'at', source, lineno, colno, error);
};