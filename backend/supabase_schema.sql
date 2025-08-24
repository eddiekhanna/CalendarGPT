-- Create table for storing Google OAuth credentials
CREATE TABLE IF NOT EXISTS google_credentials (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_uri TEXT DEFAULT 'https://oauth2.googleapis.com/token',
    client_id TEXT,
    client_secret TEXT,
    scopes TEXT[],
    expiry TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Enable Row Level Security
ALTER TABLE google_credentials ENABLE ROW LEVEL SECURITY;

-- Create policy to allow users to only see their own credentials
CREATE POLICY "Users can view own google credentials" ON google_credentials
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own google credentials" ON google_credentials
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own google credentials" ON google_credentials
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own google credentials" ON google_credentials
    FOR DELETE USING (auth.uid() = user_id);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at
CREATE TRIGGER update_google_credentials_updated_at 
    BEFORE UPDATE ON google_credentials 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column(); 