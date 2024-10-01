// JavaScript for chat interaction

const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatWindow = document.querySelector('.chat-window');
const initialView = document.querySelector('.initial-view');
const suggestions = document.querySelector('.suggestions');
const newChatIcon = document.querySelector('.new-chat-icon');

const loadingGifPath = 'static/icons/typing-gif.gif';  // Update this path if needed
const kachifoLogoPath = 'static/logo/kachifo-logo-small.svg';  // Update this path if needed

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

// Function to create chat bubbles for user and system messages
function createChatBubble(message, sender, isTyping = false) {
    const bubble = document.createElement('div');
    bubble.classList.add(sender === 'kachifo' ? 'kachifo-message' : 'user-message');
    bubble.setAttribute('aria-live', 'polite');

    // Kachifo logo for system messages
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

    // Display user input
    createChatBubble(message, 'user');
    userInput.value = '';
    userInput.style.height = 'auto';

    initialView.classList.add('hidden');
    suggestions.classList.add('hidden');
    chatWindow.classList.add('active');

    // Show the typing indicator
    const typingBubble = createChatBubble('', 'kachifo', true);

    try {
        // Concurrently fetching results from /process-query and /search
        const [processQueryResponse, searchResponse] = await Promise.all([
            fetch('/process-query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ q: message })
            }),
            fetch(`/search?q=${encodeURIComponent(message)}`)
        ]);

        if (!processQueryResponse.ok || !searchResponse.ok) {
            throw new Error(`HTTP error! processQuery: ${processQueryResponse.status}, search: ${searchResponse.status}`);
        }

        const processQueryData = await processQueryResponse.json();
        const searchData = await searchResponse.json();

        typingBubble.remove();

        // Combine both results and display
        handleResults(processQueryData, searchData);

    } catch (error) {
        console.error('Error:', error);
        typingBubble.remove();
        createChatBubble('Something went wrong. Please try again.', 'kachifo');
    }
}

function handleResults(processQueryData, searchData) {
    // Handle both the processQueryData and searchData here
    const formattedResults = `
        <strong>Process Query Results:</strong><br>
        ${processQueryData.data.results.map(item => `
            <strong>${item.source}:</strong> ${item.title}
            <br>Summary: ${item.summary}
            <br>URL: <a href="${item.url}" target="_blank">${item.url}</a>
            <br><br>
        `).join('')}
        <strong>Search Results:</strong><br>
        ${searchData.data.results.map(item => `
            <strong>${item.source}:</strong> ${item.title}
            <br>Summary: ${item.summary}
            <br>URL: <a href="${item.url}" target="_blank">${item.url}</a>
            <br><br>
        `).join('')}
    `;

    createChatBubble(formattedResults, 'kachifo');
}

// Function to handle searching for trends (GET method)
async function fetchSearchResults(query) {
    try {
        const response = await fetch(`/search?q=${encodeURIComponent(query)}`, {
            method: 'GET',
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (Array.isArray(data.results)) {
            const formattedResponse = data.results.map(item => 
                `${item.source}: ${item.title}\nSummary: ${item.summary}\nURL: ${item.url}`
            ).join('\n\n');
            createChatBubble(formattedResponse, 'kachifo');
        } else if (data.error) {
            createChatBubble(`Error: ${data.error}`, 'kachifo');
        } else {
            createChatBubble('Received an unexpected response format.', 'kachifo');
        }
    } catch (error) {
        console.error('Error fetching search results:', error);
        createChatBubble('Error fetching search results. Please try again.', 'kachifo');
    }
}

// Function to fetch recent searches (GET method)
async function fetchRecentSearches() {
    try {
        const response = await fetch('/recent_searches', {
            method: 'GET',
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        if (Array.isArray(data.data)) {
            const formattedResponse = data.data.map(search => 
                `Query: ${search.query}\nTimestamp: ${search.timestamp}`
            ).join('\n\n');
            createChatBubble(formattedResponse, 'kachifo');
        } else if (data.error) {
            createChatBubble(`Error: ${data.error}`, 'kachifo');
        } else {
            createChatBubble('Received an unexpected response format.', 'kachifo');
        }
    } catch (error) {
        console.error('Error fetching recent searches:', error);
        createChatBubble('Error fetching recent searches. Please try again.', 'kachifo');
    }
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