import { PROFILE_FRAME_OPTIONS as FRAME_OPTIONS } from '../constants/avatarFrames';
import { useAvatarPolicy } from '../hooks/useAvatarPolicy';
import React, { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';

import { useAuth, useTheme } from '../hooks/useAuth';
import api from '../services/mockApi';
import PageLoader from '../components/loading/PageLoader';
import BackupManager from '../components/BackupManager';
import {
    AvatarCropMetadata,
    Department,
    Reward,
    Role,
} from '../types';
import {
    CheckCircleIcon,
    ExclamationTriangleIcon,
    GiftIcon,
    LockClosedIcon,
    ShieldCheckIcon,
    UserIcon,
} from '../components/icons';
import { CameraIcon } from '../components/icons/CameraIcon';
import Avatar from '../components/Avatar';
import SkillsEditor from '../components/SkillsEditor';
import { getUserAvatarUrl } from '../utils/userAvatar';
import AvatarCropModal from '../components/AvatarCropModal';
import SettingsNotificationsPanel from '../components/SettingsNotificationsPanel';
import { useUnsavedChanges } from '../hooks/useUnsavedChanges';


type StatusMessage = {
    type: 'success' | 'error';
    message: string;
} | null;



const PROFILE_BADGE_STORAGE_KEY = 'owner-selected-badge-id';



const ProfileSettings: React.FC = () => {
    const { user, updateUserInContext } = useAuth();
    const avatarPolicy = useAvatarPolicy();
    const { theme, setTheme } = useTheme();

    const [loading, setLoading] = useState(true);
    const [departments, setDepartments] = useState<Department[]>([]);

    const [profileForm, setProfileForm] = useState({
        profileBio: '',
        phone: '',
        location: '',
        timezone: '',
        skills: [] as string[],
        name: '',
        employerId: '',
        departmentId: '',
    });
    const [profileStatus, setProfileStatus] = useState<StatusMessage>(null);
    const [profileSubmitting, setProfileSubmitting] = useState(false);

    const [passwordForm, setPasswordForm] = useState({
        current: '',
        next: '',
        confirm: '',
    });
    const [passwordStatus, setPasswordStatus] = useState<StatusMessage>(null);
    const [passwordSubmitting, setPasswordSubmitting] = useState(false);

    const [profileFrame, setProfileFrame] = useState<string>(() => {
        if (typeof window === 'undefined') return 'classic';
        return user?.avatarFrame ?? 'classic';
    });
    const [profilePicture, setProfilePicture] = useState<string | null>(null);
    const [collectedBadges, setCollectedBadges] = useState<Reward[]>([]);
    const [badgesLoading, setBadgesLoading] = useState(false);
    const [selectedBadgeId, setSelectedBadgeId] = useState<string>(() => {
        if (typeof window === 'undefined') return '';
        return window.localStorage.getItem(PROFILE_BADGE_STORAGE_KEY) ?? '';
    });
    const [mediaStatus, setMediaStatus] = useState<StatusMessage>(null);
    const [avatarUploading, setAvatarUploading] = useState(false);
    const [avatarUploadProgress, setAvatarUploadProgress] = useState(0);
    const [avatarCropSource, setAvatarCropSource] = useState<string | null>(null);
    const [avatarCropOpen, setAvatarCropOpen] = useState(false);
    const [pendingAvatarFile, setPendingAvatarFile] = useState<File | null>(null);
    const [skillSuggestions, setSkillSuggestions] = useState<string[]>([]);
    const [avatarProcessing, setAvatarProcessing] = useState(false);


    const [resetOtpRequested, setResetOtpRequested] = useState(false);
    const [resetConfirmation, setResetConfirmation] = useState(false);
    const [resetOtp, setResetOtp] = useState('');
    const [resetStatus, setResetStatus] = useState<StatusMessage>(null);
    const [resetLoading, setResetLoading] = useState(false);



    useUnsavedChanges(Boolean(user && !loading && (
        profileForm.profileBio !== (user.profileBio ?? '') ||
        profileForm.phone !== (user.phone ?? '') || profileForm.location !== (user.location ?? '') ||
        profileForm.timezone !== (user.timezone ?? '') || JSON.stringify(profileForm.skills) !== JSON.stringify(user.skills ?? []) ||
        profileForm.name !== (user.name ?? '') ||
        profileForm.employerId !== (user.employerId ?? '') ||
        profileForm.departmentId !== (user.departmentId ?? '') ||
        passwordForm.current || passwordForm.next || passwordForm.confirm || resetOtp ||
        avatarCropOpen || avatarUploading || avatarProcessing || profileSubmitting || passwordSubmitting || resetLoading
    )));

    useEffect(() => {
        if (!user) {
            return;
        }

        setProfileForm({
            profileBio: user.profileBio ?? '',
            phone: user.phone ?? '',
            location: user.location ?? '',
            timezone: user.timezone ?? '',
            skills: user.skills ?? [],
            name: user.name ?? '',
            employerId: user.employerId ?? '',
            departmentId: user.departmentId ?? '',
        });

    }, [user?.id, user?.name, user?.employerId, user?.departmentId, user?.profileBio, user?.phone, user?.location, user?.timezone, JSON.stringify(user?.skills)]);

    useEffect(() => {
        if (!user) {
            setProfilePicture(null);
            return;
        }
        setProfilePicture(getUserAvatarUrl(user));
        setProfileFrame(user.avatarFrame ?? 'classic');
    }, [user?.profileImageUrl, user?.avatarUrl, user?.id, user?.avatarFrame]);



    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (selectedBadgeId) {
            window.localStorage.setItem(PROFILE_BADGE_STORAGE_KEY, selectedBadgeId);
        } else {
            window.localStorage.removeItem(PROFILE_BADGE_STORAGE_KEY);
        }
    }, [selectedBadgeId]);

    useEffect(() => {
        return () => {
            if (avatarCropSource) {
                URL.revokeObjectURL(avatarCropSource);
            }
        };
    }, [avatarCropSource]);

    useEffect(() => {
        let isMounted = true;

        const hydrateBadges = async () => {
            if (!user?.claimedRewardIds || user.claimedRewardIds.length === 0) {
                if (isMounted) {
                    setCollectedBadges([]);
                    setBadgesLoading(false);
                    setSelectedBadgeId('');
                }
                return;
            }

            setBadgesLoading(true);
            try {
                const activeRewards = await api.getRewards();
                const rewardMap = new Map((activeRewards ?? []).map((reward) => [reward.id, reward]));
                const claimedIds = user.claimedRewardIds ?? [];
                const missingIds = claimedIds.filter((id) => !rewardMap.has(id));
                const missingRewards = await Promise.all(
                    missingIds.map(async (rewardId) => {
                        try {
                            return await api.getReward(rewardId);
                        } catch {
                            return null;
                        }
                    }),
                );
                missingRewards.filter(Boolean).forEach((reward) => {
                    if (reward) {
                        rewardMap.set(reward.id, reward);
                    }
                });
                if (!isMounted) {
                    return;
                }
                const orderedBadges = claimedIds
                    .map((id) => rewardMap.get(id))
                    .filter((reward): reward is Reward => Boolean(reward));
                setCollectedBadges(orderedBadges);
                setSelectedBadgeId((current) => {
                    if (orderedBadges.length === 0) {
                        return '';
                    }
                    if (current && orderedBadges.some((badge) => badge.id === current)) {
                        return current;
                    }
                    const stored =
                        typeof window === 'undefined' ? '' : window.localStorage.getItem(PROFILE_BADGE_STORAGE_KEY) ?? '';
                    if (stored && orderedBadges.some((badge) => badge.id === stored)) {
                        return stored;
                    }
                    return orderedBadges[0]?.id ?? '';
                });
            } catch (error) {
                console.error('Failed to load profile badges', error);
                if (isMounted) {
                    setCollectedBadges([]);
                }
            } finally {
                if (isMounted) {
                    setBadgesLoading(false);
                }
            }
        };

        void hydrateBadges();
        return () => {
            isMounted = false;
        };
    }, [user?.claimedRewardIds]);

    useEffect(() => {
        if (!user) {
            return;
        }

        const load = async () => {
            setLoading(true);
            try {
                const deptData = await api.getDepartments();
                setDepartments(deptData);
                const people = await api.getUsers();
                setSkillSuggestions([...new Set(people.flatMap(person => person.skills ?? []))].sort());
            } catch (error) {
                console.error('Failed to load owner settings', error);
                setProfileStatus({
                    type: 'error',
                    message: 'We could not load all owner settings. Please refresh.',
                });
            } finally {
                setLoading(false);
            }
        };

        void load();
    }, [user?.id]);



    const departmentOptions = useMemo(
        () =>
            departments
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((dept) => ({ value: dept.id, label: dept.name })),
        [departments],
    );

    const selectedBadge = useMemo(
        () => collectedBadges.find((badge) => badge.id === selectedBadgeId) ?? null,
        [collectedBadges, selectedBadgeId],
    );


    const handleProfileChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
        const { name, value } = event.target;
        setProfileForm((prev) => ({ ...prev, [name]: value }));
    };

    const handleProfileSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!user) {
            return;
        }

        setProfileSubmitting(true);
        setProfileStatus(null);

        try {
            const updated = await api.updateCurrentUserProfile(user.id, {
                name: profileForm.name.trim(),
                ...(user.role === Role.OWNER || user.role === Role.ADMIN ? {
                    employerId: profileForm.employerId.trim(),
                    department: departments.find((dept) => dept.id === profileForm.departmentId)?.name ?? '',
                } : {}),
                profileBio: profileForm.profileBio, phone: profileForm.phone.trim(), location: profileForm.location.trim(),
                timezone: profileForm.timezone.trim(), skills: profileForm.skills, updatedAt: user.updatedAt,
            });
            updateUserInContext(updated);
            setProfileStatus({
                type: 'success',
                message: 'Profile information updated successfully.',
            });
        } catch (error) {
            console.error('Profile update failed', error);
            setProfileStatus({
                type: 'error',
                message: 'Updating your profile failed. Please try again.',
            });
        } finally {
            setProfileSubmitting(false);
        }
    };

    const handleThemeChange = (value: 'light' | 'dark' | 'colorful' | 'system') => {
        setTheme(value);
    };

    const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!user) {
            return;
        }

        setPasswordStatus(null);

        if (passwordForm.next !== passwordForm.confirm) {
            setPasswordStatus({
                type: 'error',
                message: 'New password and confirmation do not match.',
            });
            return;
        }

        setPasswordSubmitting(true);
        try {
            await api.changeCurrentUserPassword(user.id, passwordForm.current, passwordForm.next);
            setPasswordStatus({
                type: 'success',
                message: 'Password updated. New credentials are active immediately.',
            });
            setPasswordForm({ current: '', next: '', confirm: '' });
        } catch (error) {
            console.error('Password update failed', error);
            setPasswordStatus({
                type: 'error',
                message: 'Password update failed. Verify your current password and try again.',
            });
        } finally {
            setPasswordSubmitting(false);
        }
    };

    const handleProfilePictureUpload = async (event: ChangeEvent<HTMLInputElement>) => {
        const input = event.target;
        const file = input.files?.[0];
        if (!file || !user) {
            return;
        }

        setMediaStatus(null);

        if (file.size > avatarPolicy.maxBytes) {
            setMediaStatus({
                type: 'error',
                message: `Please choose an image that is ${avatarPolicy.maxBytes / 1024 / 1024} MB or smaller.`,
            });
            return;
        }

        const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
        const contentType = file.type.split(';')[0].toLowerCase();

        if (!contentType || !allowedTypes.includes(contentType)) {
            setMediaStatus({
                type: 'error',
                message: 'Unsupported image type. Please upload JPEG, PNG, or WebP.',
            });
            return;
        }

        setPendingAvatarFile(file);
        setAvatarCropSource(URL.createObjectURL(file));
        setAvatarCropOpen(true);
        input.value = '';
    };

    const handleAvatarCropCancel = () => {
        setAvatarCropOpen(false);
        setPendingAvatarFile(null);
        setAvatarCropSource(null);
    };

    const handleAvatarCropComplete = async (crop: AvatarCropMetadata) => {
        if (!user || !pendingAvatarFile) throw new Error('Choose an image first.');
        setAvatarProcessing(true);
        setAvatarUploading(true);
        setAvatarUploadProgress(0);
        try {
            const updated = await api.uploadProfileAvatar(pendingAvatarFile, crop, setAvatarUploadProgress);
            updateUserInContext(updated);
            setProfilePicture(getUserAvatarUrl(updated));
            setMediaStatus({ type: 'success', message: 'Profile picture updated successfully.' });
            handleAvatarCropCancel();
        } catch (error) {
            setMediaStatus({ type: 'error', message: error instanceof Error ? error.message : 'Unable to save avatar.' });
            throw error;
        } finally {
            setAvatarProcessing(false);
            setAvatarUploading(false);
        }
    };

    const removeAvatar = async () => {
        if (!user) return;
        setAvatarProcessing(true);
        try {
            const updated = await api.updateCurrentUserProfile(user.id, { avatarAssetId: null, updatedAt: user.updatedAt });
            updateUserInContext(updated);
            setProfilePicture(null);
            setMediaStatus({ type: 'success', message: 'Picture removed. Your initials are restored.' });
        } catch (error) {
            setMediaStatus({ type: 'error', message: error instanceof Error ? error.message : 'Unable to remove picture.' });
        } finally { setAvatarProcessing(false); }
    };

    const saveFrame = async (frame: string) => {
        if (!user) return;
        setAvatarProcessing(true);
        try {
            const updated = await api.updateCurrentUserProfile(user.id, { avatarFrame: frame, updatedAt: user.updatedAt });
            updateUserInContext(updated);
            setProfileFrame(frame);
            setMediaStatus({ type: 'success', message: 'Profile frame saved.' });
        } catch (error) {
            setMediaStatus({ type: 'error', message: error instanceof Error ? error.message : 'Unable to save frame.' });
        } finally { setAvatarProcessing(false); }
    };

    const handleResetRequest = async () => {
        setResetLoading(true);
        setResetStatus(null);
        try {
            await api.requestFullResetOtp();
            setResetOtpRequested(true);
            setResetStatus({
                type: 'success',
                message: 'OTP sent to the owner mailbox. Enter it below to confirm.',
            });
        } catch (error) {
            console.error('Reset OTP request failed', error);
            setResetStatus({
                type: 'error',
                message: 'We could not send an OTP. Confirm SMTP is configured and try again.',
            });
        } finally {
            setResetLoading(false);
        }
    };

    const handleResetConfirm = async () => {
        if (!resetConfirmation) return;
        if (!resetOtp.trim()) {
            setResetStatus({
                type: 'error',
                message: 'Enter the OTP delivered to the owner email address.',
            });
            return;
        }

        setResetLoading(true);
        setResetStatus(null);
        try {
            await api.confirmFullReset(resetOtp.trim());
            setResetStatus({
                type: 'success',
                message: 'Full workspace reset complete.',
            });
            setResetOtp('');
            setResetOtpRequested(false);
            setResetConfirmation(false);
        } catch (error) {
            console.error('Reset confirmation failed', error);
            setResetStatus({
                type: 'error',
                message: 'Reset failed. Ensure the OTP is correct and not expired.',
            });
        } finally {
            setResetLoading(false);
        }
    };


    if (!user) {
        return (
            <div className="p-10">
                <p className="text-text-secondary">You need to be authenticated to view owner settings.</p>
            </div>
        );
    }

    if (loading) {
        return <PageLoader />;
    }

    return (
        <div className="space-y-8 pb-12">
                <section className="space-y-8">
                    <div className="grid gap-6 md:grid-cols-2">
                        <div className="bg-surface border border-border-color rounded-xl p-6 space-y-5 shadow-sm">
                            <div className="flex items-center gap-3">
                                <UserIcon className="h-6 w-6 text-primary" />
                                <h2 className="text-lg font-semibold text-text-primary">Profile information</h2>
                            </div>
                            {profileStatus && (
                                <StatusBanner status={profileStatus} />
                            )}
                            <form className="space-y-4" onSubmit={handleProfileSubmit}>
                                <div>
                                    <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-1">Display name</label>
                                    <input id="profile-field-1"
                                        type="text"
                                        name="name"
                                        value={profileForm.name}
                                        onChange={handleProfileChange}
                                        className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                        placeholder="Owner name"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-2">Email address</label>
                                    <input id="profile-field-2"
                                        type="email"
                                        value={user.email}
                                        disabled
                                        className="mt-1 w-full rounded-md border border-dashed border-border-color bg-muted px-3 py-2 text-text-secondary cursor-not-allowed"
                                    />
                                </div>
                                <div className="grid md:grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-3">Employer ID</label>
                                        <input id="profile-field-3"
                                            type="text"
                                            name="employerId"
                                            disabled={user.role !== Role.OWNER && user.role !== Role.ADMIN}
                                            value={profileForm.employerId}
                                            onChange={handleProfileChange}
                                            className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                            placeholder="Optional unique identifier"
                                        />
                                    </div>
                                    <div>
                                        <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-4">Department</label>
                                        <select id="profile-field-4"
                                            name="departmentId"
                                            disabled={user.role !== Role.OWNER && user.role !== Role.ADMIN}
                                            value={profileForm.departmentId}
                                            onChange={handleProfileChange}
                                            className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                        >
                                            <option value="">Unassigned</option>
                                            {departmentOptions.map((dept) => (
                                                <option key={dept.value} value={dept.value}>
                                                    {dept.label}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <label className="block text-sm text-text-secondary" htmlFor="profile-bio">Professional bio
                                    <textarea id="profile-bio" name="profileBio" value={profileForm.profileBio} maxLength={500} rows={4}
                                        onChange={handleProfileChange} className="mt-2 w-full rounded-lg border border-border-color bg-background px-3 py-2 text-text-primary" />
                                    <span className="text-xs">{profileForm.profileBio.length}/500 characters</span>
                                </label>
                                <div className="grid gap-3 sm:grid-cols-2">
                                    {(['phone', 'location', 'timezone'] as const).map(field => <label key={field} className="text-sm capitalize text-text-secondary" htmlFor={`profile-${field}`}>
                                        {field}<input id={`profile-${field}`} name={field} value={profileForm[field]} onChange={handleProfileChange}
                                            maxLength={field === 'phone' ? 50 : field === 'timezone' ? 64 : 255}
                                            className="mt-1 w-full rounded-lg border border-border-color bg-background px-3 py-2 text-text-primary" />
                                    </label>)}
                                </div>
                                <SkillsEditor value={profileForm.skills} suggestions={skillSuggestions} onChange={skills => setProfileForm(previous => ({ ...previous, skills }))} />
                                <button
                                    type="submit"
                                    disabled={profileSubmitting}
                                    className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
                                >
                                    {profileSubmitting ? 'Saving...' : 'Save profile'}
                                </button>
                            </form>
                        </div>

                        <div className="bg-surface border border-border-color rounded-xl p-6 space-y-5 shadow-sm">
                            <div className="flex items-center gap-3">
                                <ShieldCheckIcon className="h-6 w-6 text-primary" />
                                <h2 className="text-lg font-semibold text-text-primary">Theme & badge</h2>
                            </div>
                            <div>
                                <p className="text-sm font-medium text-text-secondary">Theme preset</p>
                                <div className="mt-3 grid grid-cols-2 gap-3">
                                    {(['light', 'dark', 'colorful', 'system'] as const).map((option) => (
                                        <button
                                            key={option}
                                            type="button"
                                            onClick={() => handleThemeChange(option)}
                                            className={`rounded-lg border px-4 py-3 text-left transition ${
                                                theme === option
                                                    ? 'bg-primary text-white border-transparent shadow'
                                                    : 'border-border-color text-text-secondary hover:border-primary/40 hover:text-text-primary'
                                            }`}
                                        >
                                            <p className="text-sm font-semibold capitalize">{option}</p>
                                            <p className="text-xs opacity-80">
                                                {option === 'system'
                                                    ? 'Match device preference dynamically.'
                                                    : `Force ${option} mode across the workspace.`}
                                            </p>
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div>
                                <p className="text-sm font-medium text-text-secondary">Profile badge</p>
                                {badgesLoading ? (
                                    <p className="mt-3 text-sm text-text-secondary">Loading your badges…</p>
                                ) : collectedBadges.length > 0 ? (
                                    <div className="mt-3 grid grid-cols-1 gap-3">
                                        {collectedBadges.map((badgeOption) => (
                                            <button
                                                key={badgeOption.id}
                                                onClick={() => setSelectedBadgeId(badgeOption.id)}
                                                type="button"
                                                className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition ${
                                                    selectedBadgeId === badgeOption.id
                                                        ? 'border-primary bg-primary/10 text-primary'
                                                        : 'border-border-color text-text-secondary hover:border-primary/40 hover:text-text-primary'
                                                }`}
                                            >
                                                <div className="h-12 w-12 overflow-hidden rounded-xl border border-border-color/70 bg-background">
                                                    {badgeOption.imageUrl ? (
                                                        <img src={badgeOption.imageUrl} alt={badgeOption.title} className="h-full w-full object-cover" />
                                                    ) : (
                                                        <div className="flex h-full w-full items-center justify-center">
                                                            <GiftIcon className="h-5 w-5 text-text-secondary" />
                                                        </div>
                                                    )}
                                                </div>
                                                <div>
                                                    <p className="text-sm font-semibold">{badgeOption.title}</p>
                                                    <p className="text-xs opacity-80">{badgeOption.description}</p>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                ) : (
                                    <p className="mt-3 text-sm text-text-secondary">
                                        Claim a badge from the Achievements page to equip it here.
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>
                    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                        <div className="bg-surface border border-border-color rounded-xl p-6 space-y-4 shadow-sm">
                            <div className="flex items-center gap-3">
                                <CameraIcon className="h-6 w-6 text-primary" />
                                <h2 className="text-lg font-semibold text-text-primary">Profile media</h2>
                            </div>
                            {mediaStatus && (
                                <StatusBanner status={mediaStatus} />
                            )}
                            <div className="flex items-center gap-4">
                                <Avatar user={{ ...user, avatarFrame: profileFrame }} size={96} className="h-24 w-24 text-3xl" />
                                <div className="space-y-3">
                                    <div>
                                        <label className="block">
                                            <span className="text-sm text-text-secondary">Profile picture</span>
                                            <input
                                                type="file"
                                                accept="image/jpeg,image/png,image/webp"
                                                onChange={handleProfilePictureUpload}
                                                disabled={avatarUploading || avatarProcessing}
                                                className="mt-1 block w-full text-sm text-text-secondary file:mr-4 file:rounded-md file:border-0 file:bg-primary/10 file:px-3 file:py-1 file:text-primary file:font-medium hover:file:bg-primary/20"
                                            />
                                        </label>
                                        {avatarUploading && (
                                            <p className="mt-2 text-xs text-text-secondary">
                                                Uploading {Math.round(avatarUploadProgress)}%
                                            </p>
                                        )}
                                        {avatarProcessing && !avatarUploading && (
                                            <p className="mt-2 text-xs text-text-secondary">Processing avatar...</p>
                                        )}
                                    </div>
                                    {profilePicture && <button type="button" onClick={removeAvatar} disabled={avatarUploading || avatarProcessing}
                                        className="rounded-lg border border-rose-400/40 px-3 py-2 text-sm text-rose-400 disabled:opacity-50">Remove picture</button>}
                                    <div className="rounded-lg border border-dashed border-border-color/70 p-3">
                                        {selectedBadge ? (
                                            <div className="flex items-center gap-3">
                                                <div className="h-10 w-10 overflow-hidden rounded-lg border border-border-color/60 bg-background">
                                                    {selectedBadge.imageUrl ? (
                                                        <img src={selectedBadge.imageUrl} alt={selectedBadge.title} className="h-full w-full object-cover" />
                                                    ) : (
                                                        <div className="flex h-full w-full items-center justify-center">
                                                            <GiftIcon className="h-4 w-4 text-text-secondary" />
                                                        </div>
                                                    )}
                                                </div>
                                                <div>
                                                    <p className="text-sm font-semibold text-text-primary">{selectedBadge.title}</p>
                                                    <p className="text-xs text-text-secondary">Equipped badge</p>
                                                </div>
                                            </div>
                                        ) : (
                                            <p className="text-xs text-text-secondary">Equip a badge from Theme & badge to spotlight it here.</p>
                                        )}
                                    </div>
                                </div>
                            </div>
                            <div>
                                <p className="text-sm font-medium text-text-secondary">Profile frame</p>
                                <div className="mt-3 grid grid-cols-2 gap-3">
                                    {FRAME_OPTIONS.map((frame) => (
                                        <button
                                            key={frame.value}
                                            disabled={avatarProcessing || avatarUploading}
                                            onClick={() => void saveFrame(frame.value)}
                                            type="button"
                                            className={`rounded-lg border px-4 py-3 text-left transition ${
                                                profileFrame === frame.value
                                                    ? 'border-primary bg-primary/10 text-primary'
                                                    : 'border-border-color text-text-secondary hover:border-primary/40 hover:text-text-primary'
                                            }`}
                                        >
                                            <p className="text-sm font-semibold">{frame.label}</p>
                                            <p className="text-xs opacity-80">Saved across your profile.</p>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <div className="bg-surface border border-border-color rounded-xl p-6 space-y-5 shadow-sm">
                            <div className="flex items-center gap-3">
                                <LockClosedIcon className="h-6 w-6 text-primary" />
                                <h2 className="text-lg font-semibold text-text-primary">Password reset</h2>
                            </div>
                            {passwordStatus && (
                                <StatusBanner status={passwordStatus} />
                            )}
                            <form className="space-y-4" onSubmit={handlePasswordSubmit}>
                                <div>
                                    <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-5">Current password</label>
                                    <input id="profile-field-5"
                                        type="password"
                                        value={passwordForm.current}
                                        onChange={(event) => setPasswordForm((prev) => ({ ...prev, current: event.target.value }))}
                                        className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                        required
                                    />
                                </div>
                                <div className="grid md:grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-6">New password</label>
                                        <input id="profile-field-6"
                                            type="password"
                                            value={passwordForm.next}
                                            onChange={(event) => setPasswordForm((prev) => ({ ...prev, next: event.target.value }))}
                                            className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                            required
                                        />
                                    </div>
                                    <div>
                                        <label className="text-sm font-medium text-text-secondary" htmlFor="profile-field-7">Confirm password</label>
                                        <input id="profile-field-7"
                                            type="password"
                                            value={passwordForm.confirm}
                                            onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))}
                                            className="mt-1 w-full rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                            required
                                        />
                                    </div>
                                </div>
                                <button
                                    type="submit"
                                    disabled={passwordSubmitting}
                                    className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
                                >
                                    {passwordSubmitting ? 'Updating...' : 'Update password'}
                                </button>
                            </form>
                        </div>

                        <SettingsNotificationsPanel />
                    </div>

                    {user.role === Role.OWNER && (
                    <div className="bg-surface border border-border-color rounded-xl p-6 space-y-6 shadow-sm">
                        <BackupManager requestedBy={user.name || user.email} />
                        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 space-y-3">
                            <div className="flex items-center gap-3">
                                <ExclamationTriangleIcon className="w-5 h-5 text-amber-500" />
                                <div>
                                    <p className="text-xs font-semibold uppercase tracking-wide text-red-400">Danger Zone</p><p className="text-sm font-semibold text-text-primary">Full workspace reset</p>
                                    <p className="text-xs text-text-secondary">
                                        Deletes users, departments, tasks, task comments and subtasks, task dependencies, Kanban columns, rewards, claims, achievements and notifications, then runs existing system seeding. This is irreversible. OTP expires after 10 minutes; five incorrect attempts block it.
                                    </p>
                                </div>
                            </div>
                            {resetStatus && (
                                <StatusBanner status={resetStatus} />
                            )}
                            <label className="flex items-start gap-2 text-sm text-text-secondary"><input type="checkbox" checked={resetConfirmation} onChange={event => setResetConfirmation(event.target.checked)} />I explicitly confirm deletion of the data listed above.</label>
                            {!resetOtpRequested ? (
                                <button
                                    type="button"
                                    onClick={handleResetRequest}
                                    disabled={resetLoading || !resetConfirmation}
                                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-rose-500 to-red-500 text-white font-medium hover:from-rose-600 hover:to-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                                >
                                    {resetLoading ? 'Sending OTP...' : 'Send OTP to owner email'}
                                </button>
                            ) : (
                                <div className="flex flex-wrap items-center gap-3">
                                    <input
                                        type="text"
                                        value={resetOtp}
                                        onChange={(event) => setResetOtp(event.target.value)}
                                        placeholder="Enter 6-digit OTP"
                                        className="rounded-md border border-border-color bg-background px-3 py-2 text-text-primary focus:border-primary focus:outline-none"
                                        maxLength={6}
                                    />
                                    <button
                                        type="button"
                                        onClick={handleResetConfirm}
                                        disabled={resetLoading || !resetConfirmation}
                                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-rose-500 to-red-500 text-white font-medium hover:from-rose-600 hover:to-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
                                    >
                                        {resetLoading ? 'Resetting...' : 'Confirm full reset'}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setResetOtp('');
                                            setResetOtpRequested(false);
            setResetConfirmation(false);
                                            setResetStatus(null);
                                        }}
                                        className="text-sm text-text-secondary hover:text-text-primary"
                                    >
                                        Cancel
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                    )}
                </section>


            {avatarCropOpen && avatarCropSource && (
                <AvatarCropModal
                    isOpen={avatarCropOpen}
                    imageSrc={avatarCropSource}
                    onCancel={handleAvatarCropCancel}
                    uploadProgress={avatarUploading ? avatarUploadProgress : undefined}
                    onCompleteWithMetadata={handleAvatarCropComplete}
                />
            )}
        </div>
    );
};

const StatusBanner: React.FC<{ status: StatusMessage }> = ({ status }) => {
    if (!status) return null;
    const Icon = status.type === 'success' ? CheckCircleIcon : ExclamationTriangleIcon;
    const classes =
        status.type === 'success'
            ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/40'
            : 'bg-amber-500/10 text-amber-500 border-amber-500/40';

    return (
        <div role={status.type === 'error' ? 'alert' : 'status'} className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${classes}`}>
            <Icon className="h-5 w-5 mt-0.5" />
            <span>{status.message}</span>
        </div>
    );
};

export default ProfileSettings;
