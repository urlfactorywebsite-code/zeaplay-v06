import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { getConversationTitle } from './utils/conversation';
import { useChat } from './hooks/useChat';
import ChatHeader from './components/ChatHeader';
import ChatErrorBoundary from './components/ChatErrorBoundary';
import ChatModal from './components/ChatModal';
import ChatSearchModal from './components/ChatSearchModal';
import ChatSidebar from './components/ChatSidebar';
import EmptyChatState from './components/EmptyChatState';
import MemberPanel from './components/MemberPanel';
import MessageComposer from './components/MessageComposer';
import MessageList from './components/MessageList';
import PinnedMessagesPanel from './components/PinnedMessagesPanel';
import { chatService } from './services/chatService';
import { ChatPinnedMessage } from './types';

const ChatApp: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const [replyTo, setReplyTo] = useState<ReturnType<typeof useChat>['messages'][number] | null>(null);
  const [creationMode, setCreationMode] = useState<'DIRECT' | 'GROUP' | 'SPACE' | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pinsOpen, setPinsOpen] = useState(false);
  const [pins, setPins] = useState<ChatPinnedMessage[]>([]);
  const [pinsLoading, setPinsLoading] = useState(false);
  const chat = useChat(conversationId ?? null);

  useEffect(() => {
    if (chat.selectedConversationId && chat.selectedConversationId !== conversationId) {
      navigate(`/chat/${chat.selectedConversationId}`, { replace: !conversationId });
    }
  }, [chat.selectedConversationId, conversationId, navigate]);

  useEffect(() => {
    const unread = chat.conversations.reduce((total, conversation) => total + conversation.unreadCount, 0);
    const baseTitle = document.title.replace(/^\(\d+\)\s+/, '');
    document.title = unread > 0 ? `(${unread}) ${baseTitle}` : baseTitle;
  }, [chat.conversations]);

  useEffect(() => {
    if (!chat.selectedConversationId) {
      setPins([]);
      return;
    }
    setPinsLoading(true);
    chatService.listPins(chat.selectedConversationId).then(setPins).catch(() => setPins([])).finally(() => setPinsLoading(false));
  }, [chat.selectedConversationId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === 'Escape') {
        setReplyTo(null);
        setPinsOpen(false);
        setSearchOpen(false);
        setCreationMode(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const selectConversation = (id: string) => {
    chat.setSelectedConversationId(id);
    navigate(`/chat/${id}`);
    setSidebarOpen(false);
  };

  const selectedOtherMember = useMemo(() => {
    return chat.selectedConversation?.members.find((member) => member.userId !== user?.id) ?? null;
  }, [chat.selectedConversation?.members, user?.id]);

  const selectedPresence = useMemo(() => {
    const other = chat.selectedConversation?.members.find((member) => member.userId !== user?.id);
    return other ? chat.presenceByUserId[other.userId] ?? 'OFFLINE' : 'OFFLINE';
  }, [chat.presenceByUserId, chat.selectedConversation?.members, user?.id]);

  const selectedTitle = chat.selectedConversation ? getConversationTitle(chat.selectedConversation, user) : 'this chat';
  const currentMember = chat.selectedConversation?.members.find((member) => member.userId === user?.id) ?? null;
  const canManageSelected = Boolean(currentMember && ['OWNER', 'ADMIN'].includes(currentMember.role));
  const selectedDirectInactive = Boolean(chat.selectedConversation?.type === 'DIRECT' && selectedOtherMember?.accountStatus === 'DEACTIVATED');

  const refreshPins = async () => {
    if (!chat.selectedConversationId) return;
    setPinsLoading(true);
    try {
      setPins(await chatService.listPins(chat.selectedConversationId));
    } finally {
      setPinsLoading(false);
    }
  };

  const pinMessage = async (message: ReturnType<typeof useChat>['messages'][number]) => {
    await chat.pinMessage(message);
    await refreshPins();
  };

  const unpinMessage = async (messageId: string) => {
    await chat.unpinMessage(messageId);
    await refreshPins();
  };

  return (
    <div className="chat-workspace">
      <div className="chat-shell">
        <div className={`${sidebarOpen ? 'fixed inset-0 z-40 block bg-black/60 p-3 backdrop-blur-sm' : 'hidden'} lg:static lg:block lg:bg-transparent lg:p-0 lg:backdrop-blur-0`}>
          <div className="h-full overflow-hidden rounded-2xl lg:rounded-none">
            <ChatSidebar
              currentUser={user}
              conversations={chat.conversations}
              directoryUsers={chat.directoryUsers}
              selectedConversationId={chat.selectedConversationId}
              loading={chat.loadingConversations || chat.loadingDirectory}
              presenceByUserId={chat.presenceByUserId}
              onSelectConversation={selectConversation}
              onSelectUser={(userId) => {
                void chat.startDirect(userId);
                setSidebarOpen(false);
              }}
              onOpenCreate={setCreationMode}
              onOpenSearch={() => setSearchOpen(true)}
            />
          </div>
        </div>

        <main className="chat-main">
          <ChatHeader
            conversation={chat.selectedConversation}
            currentUser={user}
            presence={selectedPresence}
            detailsOpen={detailsOpen}
            favorite={Boolean(currentMember?.isPinned)}
            onOpenSidebar={() => setSidebarOpen(true)}
            onToggleDetails={() => setDetailsOpen((value) => !value)}
            onToggleFavorite={() => {
              if (!chat.selectedConversationId || !user?.id) return;
              void chat.toggleFavorite(chat.selectedConversationId, user.id, !currentMember?.isPinned);
            }}
          />
          {chat.error && (
            <div className="chat-error-banner">{chat.error}</div>
          )}
          {chat.selectedConversation ? (
            <ChatErrorBoundary resetKey={chat.selectedConversationId}>
              <MessageList
                conversation={chat.selectedConversation}
                messages={chat.messages}
                currentUser={user}
                loading={chat.loadingMessages}
                hasMore={chat.hasMore}
                onLoadMore={() => void chat.loadMoreMessages()}
                typingUsers={chat.typingUsers.filter((name) => name !== user?.name)}
                onReply={setReplyTo}
                onRetry={chat.retryMessage}
                onToggleReaction={(message, emoji) => chat.toggleReaction(message, emoji, user?.id)}
                onEdit={chat.editMessage}
                onDelete={chat.deleteMessage}
                canManage={canManageSelected}
                onPin={(message) => void pinMessage(message)}
              />
              <MessageComposer
                disabled={!chat.selectedConversation || selectedDirectInactive}
                placeholder={`Message ${chat.selectedConversation.type === 'DIRECT' ? selectedTitle : `#${selectedTitle.toLowerCase().replace(/\s+/g, '-')}`}`}
                disabledReason={selectedDirectInactive ? 'This user is no longer active. You can view previous messages but cannot send new messages.' : undefined}
                replyTo={replyTo}
                onCancelReply={() => setReplyTo(null)}
                onSend={chat.sendMessage}
                onTyping={chat.setTyping}
                onUploadAttachment={(file, onProgress) => chat.uploadAttachment(chat.selectedConversationId!, file, onProgress)}
              />
            </ChatErrorBoundary>
          ) : (
            <EmptyChatState />
          )}
        </main>

        <MemberPanel
          conversation={chat.selectedConversation}
          currentUser={user}
          open={detailsOpen && Boolean(chat.selectedConversation)}
          presenceByUserId={chat.presenceByUserId}
          pinnedMessages={pins}
          onClose={() => setDetailsOpen(false)}
        />
      </div>

      <ChatModal
        open={Boolean(creationMode)}
        mode={creationMode ?? 'DIRECT'}
        users={chat.directoryUsers}
        currentUser={user}
        presenceByUserId={chat.presenceByUserId}
        onClose={() => setCreationMode(null)}
        onStartDirect={chat.startDirect}
        onCreateConversation={chat.createConversation}
      />
      <ChatSearchModal open={searchOpen} conversationId={chat.selectedConversationId} onClose={() => setSearchOpen(false)} onSelectConversation={selectConversation} />
      <PinnedMessagesPanel open={pinsOpen} loading={pinsLoading} pins={pins} canManage={canManageSelected} onClose={() => setPinsOpen(false)} onJump={() => setPinsOpen(false)} onUnpin={(messageId) => void unpinMessage(messageId)} />
    </div>
  );
};

export default ChatApp;
