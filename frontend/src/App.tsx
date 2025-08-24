import React, { useState, useEffect } from 'react';
import { supabase } from './lib/supabase';
import Auth from './Auth';
import Home from './Home';

function App() {
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session
    const getSession = async () => {
      const { data: { session } } = await supabase.auth.getSession();
      setUser(session?.user ?? null);
      setLoading(false);
    };

    getSession();

    // Listen for auth changes and extract Google tokens
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        console.log('Auth state change:', event, session?.user?.email);
        setUser(session?.user ?? null);
        setLoading(false);

        // Extract and store Google tokens when user signs in
        if (event === 'SIGNED_IN' && session) {
          const accessToken = session.provider_token;
          const refreshToken = session.provider_refresh_token;

          console.log('=== Google OAuth Tokens ===');
          console.log('Access Token:', accessToken ? 'Present' : 'Missing');
          console.log('Refresh Token:', refreshToken ? 'Present' : 'Missing');
          console.log('User ID:', session.user?.id);
          console.log('Provider:', session.user?.app_metadata?.provider);
          console.log('Full session:', session);
          console.log('==========================');

          // Store tokens in Supabase if we have them
          if (accessToken && session.user) {
            try {
              console.log('Attempting to store Google tokens...');
              
              // First, try to delete any existing record for this user
              const { error: deleteError } = await supabase
                .from('google_credentials')
                .delete()
                .eq('user_id', session.user.id);
              
              if (deleteError) {
                console.log('No existing record to delete or delete failed:', deleteError);
              } else {
                console.log('Deleted existing credentials record');
              }
              
              // Now insert the new record
              const { error } = await supabase
                .from('google_credentials')
                .insert({
                  user_id: session.user.id,
                  access_token: accessToken,
                  refresh_token: refreshToken,
                  client_id: '388424431581-ut72afstklmro037u0bon54da1eq0s5t.apps.googleusercontent.com',
                  scopes: ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/tasks'],
                  expiry: new Date(Date.now() + 3600000).toISOString(), // 1 hour from now
                });

              if (error) {
                console.error('Error storing Google tokens:', error);
              } else {
                console.log('✅ Google tokens stored successfully in database');
              }
            } catch (error) {
              console.error('Failed to store Google tokens:', error);
            }
          } else {
            console.log('❌ No access token available for storage');
            console.log('This might be because:');
            console.log('1. User signed in with email/password instead of Google');
            console.log('2. Google OAuth didn\'t return the expected tokens');
            console.log('3. The OAuth scopes weren\'t properly requested');
          }
        }
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  const handleAuthSuccess = () => {
    // This will be handled by the auth state change listener
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-gray-100 font-mono flex items-center justify-center">
        <div className="text-xl">Loading...</div>
      </div>
    );
  }

  return user ? <Home user={user} /> : <Auth onAuthSuccess={handleAuthSuccess} />;
}

export default App;