import React, { useState, useRef, useEffect } from 'react';
import { supabase } from './lib/supabase';
import Message from './Message';

interface Message {
  id: string;
  content: string;
  isUser: boolean;
  timestamp: Date;
}

interface HomeProps {
  user?: any;
}

function Home({ user }: HomeProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [showFileUpload, setShowFileUpload] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileMessage, setFileMessage] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const logoutButtonRef = useRef<HTMLButtonElement>(null);

  const handleLogout = async () => {
    console.log('Logout button clicked');
    
    if (isLoggingOut) {
      console.log('Logout already in progress...');
      return;
    }
    
    setIsLoggingOut(true);
    
    // Prevent multiple clicks
    if (logoutButtonRef.current) {
      logoutButtonRef.current.disabled = true;
      logoutButtonRef.current.textContent = 'Logging out...';
    }
    
    try {
      console.log('Calling supabase.auth.signOut()...');
      
      // Use a shorter timeout and more aggressive cleanup
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Logout timeout')), 3000)
      );
      
      const signOutPromise = supabase.auth.signOut();
      const result = await Promise.race([signOutPromise, timeoutPromise]) as any;
      
      console.log('signOut result:', result);
      
      // Always proceed with cleanup regardless of result
      console.log('Proceeding with logout cleanup...');
      
    } catch (error) {
      console.error('Logout exception:', error);
      console.log('Supabase signOut failed, using fallback method...');
    }
    
    // Always perform cleanup and redirect
    try {
      console.log('Clearing local storage and session...');
      
      // Clear all Supabase-related storage
      localStorage.removeItem('supabase.auth.token');
      localStorage.removeItem('sb-388424431581-ut72afstklmro037u0bon54da1eq0s5t-auth-token');
      sessionStorage.clear();
      
      // Clear any other potential auth storage
      Object.keys(localStorage).forEach(key => {
        if (key.includes('supabase') || key.includes('auth')) {
          localStorage.removeItem(key);
        }
      });
      
      console.log('Storage cleared, redirecting...');
      
      // Force redirect to auth page
      window.location.href = '/';
      
    } catch (cleanupError) {
      console.error('Cleanup failed:', cleanupError);
      // Force reload as last resort
      window.location.reload();
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize AI when component mounts
  useEffect(() => {
    const initializeAI = async () => {
      try {
        console.log('🔍 Checking Google credentials for user:', user?.id);
        
        // First check if user has Google credentials
        const credentialsResponse = await fetch(`http://127.0.0.1:5001/api/auth/check-credentials?user_id=${user?.id}`);
        const credentialsData = await credentialsResponse.json();
        
        console.log('📊 Credentials check result:', credentialsData);
        
        if (!credentialsData.has_credentials) {
          console.log('❌ No credentials found, showing setup message');
          const noCredentialsMessage: Message = {
            id: Date.now().toString(),
            content: "Welcome! I can help you manage your Google Calendar and Tasks. To get started, you'll need to sign in with Google to grant me access to your calendar and tasks. You can sign out and sign back in with Google to set this up.",
            isUser: false,
            timestamp: new Date()
          };
          setMessages([noCredentialsMessage]);
          return;
        }
        
        console.log('✅ Credentials found, initializing AI...');
        
        const response = await fetch('http://127.0.0.1:5001/api/ai/init', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            user_id: user?.id
          })
        });

        if (response.ok) {
          const data = await response.json();
          
          // Parse the structured response to extract userReply
          const aiResponse = data.response;
          
          // Find the last userReply in the response and extract just the content
          const userReplyMatch = aiResponse.match(/userReply:\s*"([^"]+)"/);
          const userReply = userReplyMatch ? userReplyMatch[1] : aiResponse;
          
          const initMessage: Message = {
            id: Date.now().toString(),
            content: userReply,
            isUser: false,
            timestamp: new Date()
          };
          setMessages([initMessage]);
        }
      } catch (error) {
        console.error('Failed to initialize AI:', error);
        const errorMessage: Message = {
          id: Date.now().toString(),
          content: "Sorry, I'm having trouble connecting to my services right now. Please try refreshing the page.",
          isUser: false,
          timestamp: new Date()
        };
        setMessages([errorMessage]);
      }
    };

    // Add a small delay to ensure OAuth tokens are stored
    const timer = setTimeout(() => {
      initializeAI();
    }, 1000); // Wait 1 second for OAuth tokens to be stored

    return () => clearTimeout(timer);
  }, [user?.id]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Check file size (limit to 10MB)
    if (file.size > 10 * 1024 * 1024) {
      alert('File size must be less than 10MB');
      return;
    }

    // Store the file and show upload modal
    setSelectedFile(file);
    setShowFileUpload(true);
    
    // Clear file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleFileSubmit = async () => {
    if (!selectedFile) return;

    setUploading(true);
    setShowFileUpload(false);

    try {
      // Create FormData for file upload
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('user_id', user?.id || '');
      
      // Add the user's message if provided
      if (fileMessage.trim()) {
        formData.append('user_message', fileMessage.trim());
      }

      // Add user message to chat if provided
      if (fileMessage.trim()) {
        const userMessage: Message = {
          id: Date.now().toString(),
          content: `📄 ${fileMessage.trim()}`,
          isUser: true,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, userMessage]);
      }

      // Call the file extraction API
      const response = await fetch('http://127.0.0.1:5001/api/file/extract', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        throw new Error('Failed to extract text from file');
      }

      const data = await response.json();
      
      // Process the AI response using the helper function
      processAIResponse(data);
      
    } catch (error) {
      console.error('Upload error:', error);
      const errorMessage: Message = {
        id: Date.now().toString(),
        content: '❌ Failed to extract text from file. Please try again.',
        isUser: false,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setUploading(false);
      setSelectedFile(null);
      setFileMessage('');
    }
  };

  const cancelFileUpload = () => {
    setShowFileUpload(false);
    setSelectedFile(null);
    setFileMessage('');
  };

  const processAIResponse = (data: any) => {
    const aiResponse = data.response;
    
    // Check if there was an API error (like missing Google credentials)
    if (data.api_result && !data.api_result.success) {
      const errorMessage = data.api_result.error || 'Unknown error occurred';
      
      // Handle specific Google credential errors
      if (errorMessage.includes('No Google credentials found')) {
        const credentialError: Message = {
          id: (Date.now() + 1).toString(),
          content: "I need access to your Google Calendar and Tasks to help you. Please sign in with Google to continue. You can sign out and sign back in with Google to grant the necessary permissions.",
          isUser: false,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, credentialError]);
        return;
      }
      
      // Handle other API errors
      const apiErrorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `I understand what you want to do, but I'm having trouble with the calendar/task operation: ${errorMessage}`,
        isUser: false,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, apiErrorMessage]);
      return;
    }
    
    // Handle successful API results with data
    if (data.api_result && data.api_result.success) {
      // Check if we have a formatted response from the API
      if (data.api_result.formatted_response) {
        const formattedMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: data.api_result.formatted_response,
          isUser: false,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, formattedMessage]);
        return;
      }
      
      // Check if we have tasks to display (fallback)
      if (data.api_result.tasks && data.api_result.tasks.length > 0) {
        const taskList = data.api_result.tasks.map((task: any) => {
          const dueDate = task.due ? new Date(task.due).toLocaleDateString() : 'No due date';
          return `• ${task.title} (Due: ${dueDate})`;
        }).join('\n');
        
        const tasksMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `📋 **Your Tasks:**\n\n${taskList}`,
          isUser: false,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, tasksMessage]);
        return;
      }
      
      // Check if we have events to display (fallback)
      if (data.api_result.events && data.api_result.events.length > 0) {
        const eventList = data.api_result.events.map((event: any) => {
          const startDate = event.start?.dateTime ? 
            new Date(event.start.dateTime).toLocaleString() : 
            event.start?.date ? new Date(event.start.date).toLocaleDateString() : 'No date';
          return `• ${event.summary} (${startDate})`;
        }).join('\n');
        
        const eventsMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `📅 **Your Events:**\n\n${eventList}`,
          isUser: false,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, eventsMessage]);
        return;
      }
      
      // If no data but success, show the API result message
      if (data.api_result.message) {
        const apiMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: data.api_result.message,
          isUser: false,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, apiMessage]);
        return;
      }
    }
    
    // Always show the AI response (userReply) regardless of API result
    // This ensures clarification messages are displayed properly
    const userReplyMatch = aiResponse.match(/userReply:\s*"([^"]+)"/);
    const userReply = userReplyMatch ? userReplyMatch[1] : aiResponse;
    
    const aiMessage: Message = {
      id: (Date.now() + 1).toString(),
      content: userReply,
      isUser: false,
      timestamp: new Date()
    };
    
    setMessages(prev => [...prev, aiMessage]);
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputMessage,
      isUser: true,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    const currentMessage = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    try {
      // Call the AI processing API
      const response = await fetch('http://127.0.0.1:5001/api/ai/process', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text: currentMessage,
          user_id: user?.id
        })
      });

      if (!response.ok) {
        throw new Error('Failed to get AI response');
      }

      const data = await response.json();
      
      // Process the AI response using the helper function
      processAIResponse(data);
      
    } catch (error) {
      console.error('AI processing error:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: "Sorry, I'm having trouble processing your message right now. Please try again.",
        isUser: false,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Get user's name from metadata or email
  const getUserName = () => {
    if (user?.user_metadata?.first_name) {
      return `${user.user_metadata.first_name} ${user.user_metadata.last_name || ''}`.trim();
    }
    return user?.email?.split('@')[0] || 'User';
  };

  return (
    <div className="min-h-screen bg-black text-gray-100 font-mono">
      <div className="max-w-4xl mx-auto h-screen flex flex-col">
        {/* Header */}
        <div className="flex justify-between items-center p-6 border-b border-gray-800">
          <h1 className="text-2xl font-bold">Hello, {getUserName()}</h1>
          <button
            ref={logoutButtonRef}
            onClick={handleLogout}
            disabled={isLoggingOut}
            className="bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white px-4 py-2 rounded transition-colors"
          >
            {isLoggingOut ? 'Logging out...' : 'Logout'}
          </button>
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.map((message) => (
            <Message
              key={message.id}
              content={message.content}
              isUser={message.isUser}
              timestamp={message.timestamp}
            />
          ))}
          {isLoading && (
            <div className="flex justify-start mb-4">
              <div className="bg-gray-700 text-gray-100 px-4 py-2 rounded-lg">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Message Input */}
        <div className="p-6 border-t border-gray-800">
          <form onSubmit={handleSendMessage} className="flex space-x-4">
            <input
              ref={fileInputRef}
              type="file"
              accept="*/*"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg transition-colors flex items-center"
            >
              {uploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                  Uploading...
                </>
              ) : (
                <>
                  📄
                </>
              )}
            </button>
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              placeholder="Type your message..."
              disabled={isLoading}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-gray-100 focus:outline-none focus:border-gray-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!inputMessage.trim() || isLoading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white px-6 py-2 rounded-lg transition-colors"
            >
              Send
            </button>
          </form>
        </div>

        {/* File Upload Modal */}
        {showFileUpload && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-gray-800 p-6 rounded-lg max-w-md w-full mx-4">
              <h3 className="text-lg font-bold mb-4">Upload File</h3>
              <div className="mb-4">
                <p className="text-sm text-gray-300 mb-2">File: {selectedFile?.name}</p>
                <textarea
                  value={fileMessage}
                  onChange={(e) => setFileMessage(e.target.value)}
                  placeholder="Add a message about this file (optional)..."
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 focus:outline-none focus:border-gray-500 resize-none"
                  rows={3}
                />
              </div>
              <div className="flex space-x-3">
                <button
                  onClick={handleFileSubmit}
                  disabled={uploading}
                  className="flex-1 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white px-4 py-2 rounded-lg transition-colors"
                >
                  {uploading ? 'Uploading...' : 'Upload'}
                </button>
                <button
                  onClick={cancelFileUpload}
                  disabled={uploading}
                  className="flex-1 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-500 text-white px-4 py-2 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Home; 