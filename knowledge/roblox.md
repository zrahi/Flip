# Roblox development knowledge

## Roblox scripting basics
KEYS: *roblox
- Luau: Script (server, ServerScriptService), LocalScript (client: StarterPlayerScripts, StarterGui, StarterCharacterScripts), ModuleScript (shared code; ReplicatedStorage for both sides, ServerStorage/ServerScriptService for server only).
- Get services with game:GetService("Players"). Use task.wait/task.spawn/task.delay (not wait/spawn/delay). Use :WaitForChild on the client for things that replicate.
- Prefer typed Luau (--!strict) for bigger code, local functions, early returns, and connections you :Disconnect() when done.
- Write complete, runnable code in ```lua blocks and say where each script goes (service + script type).

## Client/server security
KEYS: remote, remoteevent, remotefunction, fireserver, fireclient, onserverevent, exploit, exploiter, hacker, cheat, secure, security, validate, validation, trust, anti cheat, anticheat, shop, buy, purchase, damage, give, reward, currency, coins, cash
- Never trust the client. The client only asks ("I want to buy X"); the server checks everything (does the item exist, can they afford it, cooldown, distance, ownership) and does the change.
- RemoteEvent handlers: first arg is the Player (added by Roblox, can't be faked). Type-check every other argument (typeof), clamp numbers, reject NaN/inf, rate-limit spammy remotes.
- Never let the client send amounts of money/damage/XP to apply. Never put secrets or admin checks in LocalScripts or ReplicatedStorage.
- Avoid RemoteFunction server→client InvokeClient (a client can hang the server). Use RemoteEvents instead.
- Damage/hit detection: client may request, server verifies range and line of sight (raycast) and weapon cooldown.

## DataStores and saving
KEYS: datastore, data store, save, saving, load, loading, profile, profileservice, profilestore, persist, leaderstats, leaderstat, getasync, setasync, updateasync, bindtoclose
- DataStoreService:GetDataStore("Name"). Wrap GetAsync/SetAsync/UpdateAsync in pcall and retry with backoff; they fail sometimes.
- Prefer UpdateAsync for values that change (avoids overwriting newer data). Save on PlayerRemoving and in game:BindToClose (wait for saves to finish, a few seconds max).
- Don't save every change: autosave every few minutes plus on leave. Keys like "Player_" .. player.UserId (not names).
- Session locking matters for trading/duplication-sensitive games (ProfileStore handles this).
- leaderstats: a Folder named "leaderstats" under the Player with IntValue/NumberValue children shows on the leaderboard. Create it on the server in Players.PlayerAdded.
- Studio: enable "Enable Studio Access to API Services" in Game Settings to test DataStores.

## Marketplace and monetization
KEYS: marketplaceservice, gamepass, game pass, developer product, dev product, robux, processreceipt, promptpurchase, userownsgamepassasync, premium
- Game passes: MarketplaceService:UserOwnsGamePassAsync(userId, id) on the server (pcall), and PromptGamePassPurchaseFinished to grant right after buying.
- Developer products: set MarketplaceService.ProcessReceipt once on the server; grant the item, save, then return Enum.ProductPurchaseDecision.PurchaseGranted. Return NotProcessedYet if saving failed. Make it idempotent using receiptInfo.PurchaseId.

## UI
KEYS: gui, ui, screengui, frame, textbutton, textlabel, imagebutton, scale, offset, uicorner, uilistlayout, uigridlayout, tween, tweenservice, menu, button, hud
- ScreenGui in StarterGui; LocalScripts drive UI. Use Scale sizes (with UIAspectRatioConstraint) so it works on phones; UIListLayout/UIGridLayout/UIPadding for layout; UICorner/UIStroke for style.
- TweenService:Create(obj, TweenInfo.new(0.25, Enum.EasingStyle.Quad), {Position = ...}):Play() for smooth UI.
- ResetOnSpawn = false for UIs that shouldn't reset when the character dies.

## Characters, animation, tools, physics
KEYS: character, humanoid, animation, animator, animate, tool, tools, npc, pathfinding, pathfindingservice, raycast, physics, velocity, bodyvelocity, linearvelocity, constraint, weld, collision, collisiongroup, hitbox, touched, proximityprompt, pathfind
- Character: player.CharacterAdded; humanoid = character:WaitForChild("Humanoid"). Play animations through humanoid:FindFirstChildOfClass("Animator"):LoadAnimation(anim).
- Tools: Tool in StarterPack/Backpack, Handle part, Activated event (client) → RemoteEvent → server validates.
- Raycasting: workspace:Raycast(origin, direction, RaycastParams) with FilterDescendantsInstances. Prefer raycasts/spatial queries over .Touched for hitboxes.
- Movement: use constraints (LinearVelocity, AlignPosition, AlignOrientation) instead of deprecated BodyMovers.
- PathfindingService:CreatePath({AgentRadius=..., AgentCanJump=true}); path:ComputeAsync(start, goal) in pcall; walk waypoints with Humanoid:MoveTo and MoveToFinished; recompute on path.Blocked.
- ProximityPrompt for interact buttons (Triggered fires on the server with the player).

## Performance
KEYS: lag, performance, optimize, optimise, fps, memory, streaming, streamingenabled, heartbeat, renderstepped, loop, while true
- Avoid per-frame work on the server; use events instead of while true loops; RunService.Heartbeat for physics-rate logic, RenderStepped only for camera/visual client code.
- StreamingEnabled for big maps. Anchor static parts, reduce unions/meshes' collision fidelity, use CollisionGroups.
- Pool/reuse parts instead of creating and destroying hundreds per second; Debris:AddItem for temporary effects.
