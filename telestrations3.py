#!/usr/bin/env python3

# discord stuff; commands module isn't really necessary but I cba to look up how to start the bot normally.
import discord
from discord.ext import commands

# for shuffling the player lists
import random

# for rebooting the bot
import os
import sys

# for saving to file
import pickle

intents = discord.Intents.default()
# need this intent in order to see who has reacted to a message, I think.
intents.members = True

# I initialise the bot as a commands bot even though commands get overridden by my on_message code.
client = commands.Bot(command_prefix='t!',intents=intents)


# dictionary of for each user;
# lookup by user id, gives a dictionary of
# "confirm_msg" - message to confirm on submit
# "to_confirm" - the content for the above
# "pile" - a list of 'books', each of which a dictionary with
#					"content" - a list of the contents
#					"authors" - a list of the authors of each content
#					"players" - list of players using the book
#					"start_pindex" - index of player who started the book
#					"start_channel" – channel in which the game command was sent
users = {}

# list of the ids of signup sheet messages, and a dict of the corresponding hosts keyed by those ids.
signup_sheets = [889503997872984074,889085567587975259,890188623230668870,890535271798566912,890381310206550036]
hosts = {889503997872984074:282853440487424001,889085567587975259:282853440487424001,890188623230668870:282853440487424001,890535271798566912:282853440487424001,890381310206550036:282853440487424001}

results_lock = False

MAX_PILE = 20

# for timing out
import asyncio
timers = {}


#set correct working dir
cwd = os.path.dirname(__file__)
os.chdir(cwd)

# function that saves all the game data to file.
# does not save the signup sheet data yet, which may cause problems but eh.
def save(users):
	with open("telestrations3.dat", 'wb') as f:
		pickle.dump(users, f)
	#print(users, "saved to file.")

# when the bot boots up, load all the game data from file.
@client.event
async def on_ready():
	global users
	try:
		with open("telestrations3.dat", 'rb') as f:
			users = pickle.load(f)
	except Exception as e:
		users = {}
		print(e)
		save(users)
	print("ready")
	
	while True:
		for uid,data in users.items():
			ts = len(data["pile"])
			if ts == 0:
				continue
			usr = await client.fetch_user(uid)
			try:
				await send_task(usr,True)
			except:
				print("couldn't send task to", uid)
			print ("Reminded",uid)
		print("sleeping...")
		await asyncio.sleep(43200)
		print("awake!")

def latin_square ( players ):
	n = len(players)
	# create base square
	cols = []
	pcopy = players.copy()
	for p in players:
		cols.append(pcopy.copy())
		# cycle pcopy round, assuming that pcopy[0] == p
		pcopy.pop(0)
		pcopy.append(p)

	# shuffle rows
	shuffled_i = [i for i in range(n)]
	random.shuffle(shuffled_i)
	for j in range(n):
		cols[j] = [ cols[j][i] for i in shuffled_i]
	
	return cols

# function to start a game; channel is the channel to post results in, players is a list of User objects
async def start(channel,players):
	global users
	
	# can't play with fewer than 3 players...
	if len(players) < 3:
		await channel.send("Sorry, you can't play Telestrations with fewer than 3 players!")
		return
	
	
	threads = latin_square([p.id for p in players])
	mentions = ""
	
	for t in threads:
		mentions+=f" <@{t[0]}>"
		
		# create a new game; if the user is new then also initialise the other data about the player in the game data dict (`users`).
		if not (t[0] in users.keys()):
			users[t[0]] = {"pile" : [],
							"confirm_msg" : None,
							"to_confirm" : None,
							"waiting":True}
		users[t[0]]["pile"].append({"players": t,
									"content":[],
									"authors":[],
									"start_channel":channel.id,
									"current_pindex":0})
		
		# give prompts if necessary.
		asyncio.create_task(check_pile(t[0]))
	
	# give feedback in the channel where the game was started;
	# I don't have it ping people atm because it doesn't seem necessary,
	# but I might make it list the players for clarity at some point.
	await channel.send(content=f"A game of Telestrations has started -{mentions}, check your DMs! The results of the game will be posted here at the end.")
	
	# backup game data to file.
	save(users)

# function called by the "what is the status of telestrations" command
# lists how many tasks each person has. Ignores users with no tasks.
async def give_status(msg):
	# header of the status text
	#text = "Current game status is:\n"
	text=""
	
	# list of users to ping; originally the bot only pinged people with ≥ tasks
	# HOWEVER at the moment it is set to ping no-one.
	# unfortunately this breaks the mentions on mobile.
	ping_usrs = []
	
	for uid,data in users.items():
		# I use the "waiting" flag to determine whether or not a user has tasks.
		# there is a _small_ chance of this causing a glitch, perhaps, as a user with tasks will briefly be set to `waiting` when they finish a task.
		if not data["waiting"]:
			# get the `User` object of the player for the purposes of the `AllowedMentions` below.
			# I used to fetch_member here to use the .mention attribute,
			# but I realised "manually" creating the mention is better (thx Jamal!).
			usr = await client.fetch_user(uid)
			
			if len(data["pile"]) >= 2: # only ping players with ≥2 tasks
				ping_usrs.append(usr)
				
				# the variable `s` is to change whether the text is singular or plural ("task" vs. "tasks") as appropriate.
				s = "s"
			else:
				s = ""
			
			# append this player and their status to the status message.
			text += f"<@{uid}> – {str(len(data['pile']))} task{s} pending.\n"
	
	# send the status message with, currently, no pings.
	#await msg.channel.send(content=text,allowed_mentions=discord.AllowedMentions(users=ping_usrs,everyone=False,roles=False,replied_user=False))
	embed=discord.Embed(title="Current Telestrations Status", description=text)
	await msg.channel.send(embed=embed,delete_after=120)
	try:
		await msg.delete()
	except:
		pass

# function called by the "what are the active telestrations games" command.
# this (in theory) lists people left for each game.

DISCORD_EMBED_LIMIT = 4096

async def list_active_threads(msg):
	# status message header
	#text = "Active threads:\n"
	text = ""
	page = 1
	
	# iterate through each player's pile; this *shouldn't* have any double counting or missing games.
	for uid,data in users.items():
		for game in data["pile"]:
			# list the players from the game's list of players, stating from whoever has it currently, by mention.
			# as in the other status command this will be broken on mobile since I disable pings.
			
			game_line = "•"
			separator = ""
			
			r = game["current_pindex"]
			while r < len(game["players"]) and (not (r == len(game["players"])-1 and r%2==1)):
				game_line += f"{separator}<@{game['players'][r]}>"
				separator = " → "
				r+=1 # need to manually increment the index
			
			text2 = text + game_line
			
			if len(text2) >= DISCORD_EMBED_LIMIT:
				embed=discord.Embed(title=f"Active Telestrations Games (page {page})", description=text)
				await msg.channel.send(embed=embed,delete_after=120)
				text = game_line + "\n"
				
				page += 1
			else:
				text = text2 + "\n"
	
	# send the status message.
	embed=discord.Embed(title=f"Active Telestrations Games (page {page})", description=text)
	await msg.channel.send(embed=embed,delete_after=120)
	try:
		await msg.delete()
	except:
		pass

# function called when people ask the rules of telestrations.
# simply sends the hard-coded message written below.
async def tell_rules(messageble):
	rules = """```First you give a secret word, and then either you or the next player draws* this, depending on the next number of players.
The next player guesses the drawing, then the player after that draws the guess, and so on, going through everyone in the game.
When the last player has guessed, the results are then posted in EggSoc.
*When you are prompted to "draw", you need to send an image to bot, e.g. drawn in MS Paint (alternatively you could draw on paper and photograph it).
Traditionally, letters and numbers aren't allowed in Telestrations, but personally I think they should be allowed within reason, especially if they are used in an amusing way.```"""
	await messageble.send(rules)

# the event that deals with commands and also people sending secret words/guesses/drawings to the bot.
@client.event
async def on_message(msg):
	global users
	global signup_sheets
	global hosts
	
	# ignore messages by the bot itself
	if msg.author.id == client.user.id:
		return
	
	# want all commands to be case-insensitive
	case_ins_msg = msg.content.lower()
		
	# (old) start command, where you @ everyone you want to play with.
	if case_ins_msg.startswith("start telestrations with "):
		# add direct mentions
		players = msg.mentions.copy()
		
		# add role mentions;
		# we iterate through all the arguments after the "start telestrations with" part of the command,
		# and check if they correspond to the mention for a role.
		# if so, add the players who weren't mentioned directly.
		chars = msg.content.split(" ")
		for r in chars[3:]:
			try:
				T_role = discord.utils.get(msg.channel.guild.roles, mention=r)
				for m in T_role.members:
					if not (m in players):
						players.append(m)
			except:
				pass
		
		# also add the player who called the command if they didn't (directly or otherwise) tag themselves.
		if not (msg.author in players):
			players.append(msg.author)
		
		# only let me call this command (temporarily for testing purposes)
		if msg.author.id == 120125811259998208:
			# start the game in the channel the command was called with the players found above.
			await start(msg.channel,players)
		
		return
		
	# command to create a "signup sheet" for telestrations; the new method of starting games. 
	elif case_ins_msg == "request signups for telestrations" or case_ins_msg in ("telestart","telestartions","t!start"):
		# create the signup sheet, including reactions to make the UI easier for people.
		embed=discord.Embed(title="React ✅ if you want to play telestrations.", description=f"({msg.author.mention}: react ▶️ to start the game)")
		embed.set_author(name=f"{msg.author.name}#{msg.author.discriminator}", icon_url=msg.author.avatar_url)
		
		#signup = await msg.channel.send(content=f"{msg.author.mention} wants to start a game of telestrations... React ✅ to this message if you want to play.\n({msg.author.mention}: react ▶️ to this message to start the game)")
		
		# get the ping for the telestrations role, but don't break if no such role exists
		try:
			T_role = discord.utils.get(msg.channel.guild.roles, name="Telestrations Enjoyers")
			mention = T_role.mention
		except:
			mention = ""
		
		signup = await msg.channel.send(content=mention,embed=embed)
		await signup.add_reaction("✅")
		await signup.add_reaction("▶")
		
		# record that this signup sheet exists, and also who requested its creation.
		signup_sheets.append(signup.id)
		hosts[signup.id] = msg.author.id
		
		return
		
	# command to list the number of tasks people have.
	elif case_ins_msg.startswith("what is the status of telestrations") or case_ins_msg in ("telestatus","t!status","t!tasks"):
		await give_status(msg)
		return
		
	# command to list the currently active "books".
	elif case_ins_msg.startswith("what are the active telestrations games") or case_ins_msg in ("threadestrations","t!threads"):
		await list_active_threads(msg)
		return
		
	# command to read the rules of the game.
	elif case_ins_msg.startswith("what are the rules of telestrations"):
		await tell_rules(msg.channel)
		return
		
	# easter egg command
	elif case_ins_msg.startswith("what is the status of my mental health"):
		await msg.channel.send("idk but have a hug anyway https://tenor.com/view/hug-virtual-hug-hug-sent-gif-5026057")
		
	# commands to shut down / reboot this programme for the purposes of updating.
	# only I can run these commands.
	elif case_ins_msg == "t!restart":
		if msg.author.id == 120125811259998208:
			await msg.channel.send ("Rebooting Telestrations...")
			await client.close()
			file_path = os.path.abspath(__file__)
			os.system("nohup python3 -u \""+file_path+"\" &")
			sys.exit()
	elif case_ins_msg == "t!shutdown":
		if msg.author.id == 120125811259998208:
			await msg.channel.send ("Shutting down Telestrations...")
			await client.close()
			sys.exit()
	
	# note that in the below, msg.channel.recipient will throw an error outside of DMs,
	# thus the following cases automatically only work in DMs.
	
	# command to skip a task (in DMs).
	elif case_ins_msg == "skippity skip" or case_ins_msg == "teleskiptions":
		user = msg.channel.recipient
		if len(users[user.id]["pile"]) == 0:
			await user.send("Smh my head you don't even have a task to skip!")
		else:
			await move_on(user,True)
		return
		
	# command to move a task to the back of ones pile (in DMs).
	# I could make the code more compact here but this seems more readable to me.
	elif case_ins_msg == "procrastinate" or case_ins_msg == "procrastrinations":
		user = msg.channel.recipient
		if len(users[user.id]["pile"]) == 0:
			await user.send("Smh my head you can't procrasinate with no tasks!")
		elif len(users[user.id]["pile"]) == 1:
			await user.send("You only have one task at the moment!")
		else:
			task = users[user.id]["pile"][0]
			users[user.id]["pile"].pop(0)
			users[user.id]["pile"].append(task)
			users[user.id]["waiting"] = True
			await check_pile(user.id)
		return
	elif case_ins_msg in ("t!givetask","t!gt"):
		user = msg.channel.recipient
		await send_task(user, False)
	
	# case for, essentially, people sending guesses and drawings to the bot.
	else:
		
		try:
			# get the player who sent the message; should throw an error out of DMs
			p_c = msg.channel.recipient
		except:
			# outside of DMs, do nothing.
			return
		
		try:
			if msg.reference.message_id != users[p_c.id]["confirm_msg"]:
				return
		except:
			pass
		
		# ignore the message if the player has no tasks.
		if len(users[p_c.id]["pile"]) == 0:
			#await p_c.send(content="""The previous player is not ready yet.""")
			return
		
		# case where the player has ≥1 task.
		else:
			# there are essentially two cases here; either the bot expects text or it expects an image.
			# this can be determined by whether the number of "pages" in the book is odd (image) or even (text).
			# this affects both which part of the message the bot should interpret as its content,
			# and the text of the confirmation message.
			l = len(users[p_c.id]["pile"][0]["content"])
			if l % 2 == 0: # this is the case where the player has to GUESS or write the inital word
				users[p_c.id]["to_confirm"] = msg.content
				
				# the text of the confirmation message is slightly different in the first round.
				if l == 0:
					#act = "secret word or phrase"
					embed=discord.Embed(title="Confirm secret word",description=f"React ✅ to this message to confirm you wish to submit the secret word **{users[p_c.id]['to_confirm']}**")
				else:
					#act = "guess"
					embed=discord.Embed(title="Confirm guess",description=f"React ✅ to this message to confirm you wish to submit the guess **{users[p_c.id]['to_confirm']}**")
					embed.set_thumbnail(url=users[p_c.id]["pile"][0]["content"][-1])
			else:
				users[p_c.id]["to_confirm"] = msg.attachments[0].url
				#act = "drawing"
				embed=discord.Embed(title="Confirm drawing",description=f"React ✅ to this message to confirm you wish to submit the drawing")
				embed.set_author(name=users[p_c.id]["pile"][0]["content"][-1])
				embed.set_image(url=users[p_c.id]["to_confirm"])
			# `act` is actually meant to be a noun.
			
			# try to delete prev. confirmation message.
			try:
				cmsg = await msg.channel.fetch_message(users[p_c.id]["confirm_msg"])
				await cmsg.delete()
			except:
				pass
			
			# send confirmation message, including the tick react for convenience,
			# and save its id in the user's data.
			#cmsg = await p_c.send(content=f"React ✅ to this message to confirm you wish to submit the following {act}:\n{users[p_c.id]['to_confirm']}")
			cmsg = await p_c.send(embed=embed)
			await cmsg.add_reaction("✅")
			users[p_c.id]["confirm_msg"] = cmsg.id
			
			# save data to file.
			save(users)


async def timeout_player(pid):
	print(f"started timeout for {pid}")
	await asyncio.sleep(172800)
	user = await client.fetch_user(pid)
	await user.send("You have been timed out of this task!")
	await move_on(user,True)

# function to check if a player is waiting, and then send them a task if they are.
# this is called on a player whenever 1) they confirm a submission for a task, (see `move_on`)
# and 2) whenever a "book" is added to their pile,
# either by a game starting (see `start`) or by the "previous" player confirming a submission. (see `move on`)
async def check_pile(pid):
	global users
	# get the player's `User` object for the purpose of sending them messages.
	user = await client.fetch_user(pid)
	
	# if the player's pile is empty tell them to wait.
	# This case should only happen when the player finishes a task.
	if len(users[pid]["pile"]) == 0:
		await user.send("Please await your next task.")
		users[pid]["waiting"] = True # flag the player as waiting so they can receive a task.
	
	# otherwise, if the player has pending tasks but is waiting, send them their next task.
	elif users[pid]["waiting"]:
		await send_task(user, False)
		#timers[pid] = asyncio.create_task(timeout_player(pid))
		
# split up from the above for use in periodic reminders
async def send_task(user : discord.User,reminder=False):
	global users
	pid = user.id
	# as with the confirmation message, there are different cases for which prompt should be sent.
	# here both images AND text are internally text; the former will be a URL,
	# so only the text need change.
	l = len(users[pid]["pile"][0]["content"])
	if l == 0: # prompt for secret word. Also contains info about the game.
		embed=discord.Embed(title="A new game of Telestrations has begun! To start, enter an initial prompt.",description="""
If you can't think of one, you may want to use https://www.wordgenerator.net/pictionary-word-generator.php""")
		embed.add_field(name="Rules", value="If you don't know the rules, type `what are the rules of telestrations?`.", inline=True)
		embed.add_field(name="Skip", value="To skip a round (and push it onto the next player), type `Skippity Skip`.", inline=True)
		embed.add_field(name="Cycle tasks", value="To cycle through your tasks, type `Procrastinate` to view the next one instead.", inline=True)
	elif l % 2 == 0: # prompt to guess.
		embed=discord.Embed(title="Guess the drawing")
		embed.set_image(url=users[pid]['pile'][0]['content'][-1])
	else: # prompt to draw.
		embed=discord.Embed(title="Draw",description=users[pid]['pile'][0]['content'][-1])
		embed.set_footer(text="(upload an image file)")
	if reminder:
		await user.send(content="**Reminder**: you have a task pending: (Note you can type `Procrastinate` to cycle through your tasks)",embed=embed)
	else:
		await user.send(embed=embed)
	
	users[pid]["waiting"] = False


# the event that deals with the various actions associated with adding reactions to messages,
# namely 1) confirming submissions and 2) starting the game from a "signup sheet".
@client.event
async def on_raw_reaction_add(payload):
	global users
	global signup_sheets
	global hosts
	
	user = await client.fetch_user(payload.user_id)
	chan = await client.fetch_channel(payload.channel_id)
	msg = await chan.fetch_message(payload.message_id)
	
	reaction = payload.emoji
	
	# ignore the bot's own reactions.
	if client.user.id == user.id:
		return
	
	# case where the reaction is to confirm a submission.
	if str(reaction) == "✅" and msg.id == users[user.id]["confirm_msg"]:
		# delete the confirmation message
		"""cmsg = await user.fetch_message (users[user.id]["confirm_msg"])
		await cmsg.delete()""" # (commented out since I put this in the `move_one` function now)
		
		# stop the user being timed out
		"""try:
			timers[user.id].cancel()
		except Exception as e:
			print(e)"""
		
		# add the secret word or guess or img to the book the player is currently working on,
		# also record that they are the author of this content.
		users[user.id]["pile"][0]["content"].append(users[user.id]["to_confirm"])
		users[user.id]["pile"][0]["authors"].append(user.id)
		
		# move the player's current book to the next player,
		# or finish the game if there isn't one.
		await move_on (user,False)
		
		return
	
	# prevent signups when too many tasks
	elif str(reaction) == "✅" and msg.id in signup_sheets:
		if len(users[user.id]["pile"]) > MAX_PILE and hosts[msg.id] != user.id:
			await msg.remove_reaction("✅",user)
			await user.send(content=f"_You were removed from the signup sheet as you have over {MAX_PILE} tasks pending._",delete_after=60)
	
	# case where the reaction is to start a game. must be triggered by whoever requested the signup sheet.
	elif str(reaction) == "▶" and msg.id in signup_sheets and hosts[msg.id] == user.id:
		# find all the users who agreed to play the game.
		# I'm going off the assumption that the first reaction will always be the tick reaction,
		# since the bot adds this immediately after the message is sent.
		players = []
		mentions = ""
		async for p in msg.reactions[0].users():
			if p.id != client.user.id: # ignore the bot's own tick.
				players.append(p)
				mentions += f"{p.mention} "
				
		# add the host to this list if they aren't on it.
		host_usr = await client.fetch_user(hosts[msg.id])
		if not (host_usr in players):
			players.append(host_usr)
			mentions += f"{host_usr.mention} "
		
		# if too few players don't start
		if len(players) < 3:
			await host_usr.send(content="_You can't start a game of telestrations with fewer than 3 players._", delete_after=10)
			return
		
		# delete the signup sheet; first from the list of signup sheets and dict of hosts, then from discord.
		signup_sheets.remove(msg.id)
		hosts.pop(msg.id)
		
		try:
			await msg.embeds[0].set_field_at(index=0,name="Telestrations Signup Sheet",value="{mentions}signed up for a game of Telestrations which already started.")
		except Exception as e:
			print(f"line 464: {e}")
			await msg.delete()
		
		# start a game with the players determined as above.
		await start(chan, players)
		return

# function to move a player's current task to the next player, or otherwise end the game.
async def move_on (user,skipped):
	global users
	
	# try to delete prev. confirmation message.
	try:
		cmsg = await user.fetch_message(users[user.id]["confirm_msg"])
		await cmsg.delete()
	except:
		pass
	
	# flag the user as waiting for their next task
	users[user.id]["waiting"] = True
	
	# the "next" player's index.
	# we calculate it here because it is useful in determining if we are in the end state.
	nextpi = users[user.id]["pile"][0]["current_pindex"] + 1
	
	# END STATE is determined by either
	# 1) running out of players or
	# 2) the penultimate player having just guessed.
	np = len(users[user.id]["pile"][0]["players"])
	if (nextpi >= np) or ( (nextpi == np-1) and ( (len(users[user.id]["pile"][0]["content"]) % 2) == 1) ):
		
		book = users[user.id]["pile"][0]
		
		# delete the book from memory.
		users[user.id]["pile"].pop(0)
		
		# send the player their next task. 
		await check_pile(user.id)
		
		#task = asyncio.create_task( disp_results(users[user.id]["pile"][0]) )
		await disp_results(book)
		
		# save game data to file.
		save(users)
		
		# exit the function, since we don't want to now immediately transfer the player's new current task to the next player!
		return
	
	# we have different rules depending on whether the number of players is odd or even.
	# in the even case, players draw their own secret word.
	if False and (len(users[user.id]["pile"][0]["content"]) == 1 and (len(users[user.id]["pile"][0]["players"])% 2 == 0)): # for now set this condition to always fail
		# don't transfer over the book to the next player
		await check_pile(user.id)
	else:
		# in the remaining cases, we want to transfer the player's current book to the next player.
		
		p_n_id = users[user.id]["pile"][0]["players"][nextpi] # next player's ID
		
		if skipped:
			users[user.id]["pile"][0]["players"].pop(users[user.id]["pile"][0]["current_pindex"])
		else:
			users[user.id]["pile"][0]["current_pindex"] = nextpi # important for the book to know who currently has it
		
		users[p_n_id]["pile"].append(users[user.id]["pile"][0]) # add book to next player's pile
		users[user.id]["pile"].pop(0) # remove book from current player's pile.
		
		# give the current player, and the player we just transferred a book to, their tasks, if they are waiting. 
		await check_pile(p_n_id)
		await check_pile(user.id)
	
	# save game data to file
	save(users)
	
async def disp_results (book):
	global results_lock
	
	# fetch the `Channel` object for the channel the game was started in, in order to message it.
	start_channel = await client.fetch_channel(book["start_channel"])
	
	# get the ping for the telestrations role, but don't break if no such role exists
	try:
		T_role = discord.utils.get(start_channel.guild.roles, name="Telestrations Enjoyers")
		mention = T_role.mention
	except:
		mention = "And"
	
	# header of the results message. The messages are separate so that the image links embed properly.
	#await start_channel.send(f"{mention} we have some results!")
	
	# `extra` flags if the first player went twice (drew their own word).
	if len(book["content"]) > len(book["players"]):
		extra = True
	else:
		extra = False
	
	embeds = []
	mentions = ""
	
	# iterate over the content of the game
	r = 0
	for media in book["content"]:
		usr = await client.fetch_user(book["authors"][r])
		mentions+= f"{usr.mention} "
		
		# as usual there are three cases for the text.
		if r == 0:
			embed=discord.Embed(description=f"<@{usr.id}> gave the secret word **{media}**")
		elif r%2 == 0:
			#act = "guessed"
			embed=discord.Embed(description=f"<@{usr.id}> guessed **{media}**")
		else:
			embed=discord.Embed(description=f"<@{usr.id}> drew")
			embed.set_image(url=media)
			
		embed.set_author(name=f"{usr.name}#{usr.discriminator}",icon_url=usr.avatar_url,url=f"https://discordapp.com/users/{usr.id}")
		
		embeds.append(embed)
		
		# reveal the "page"; the author is pinged.
		#await start_channel.send(f"<@{users[user.id]['pile'][0]['authors'][r]}> {act} {media}")
		#await start_channel.send(embed=embed)
		
		# increment as the VERY LAST THING
		r+=1
	
	while results_lock:
		await asyncio.sleep(1)
	
	# prevent results clashes
	results_lock = True
	
	try:
		hmsg = await start_channel.send(f"{mentions}{mention} we have some results!")
		await hmsg.edit(content=f"{mention} we have some results!")
	except:
		pass
	
	for embed in embeds:
		await start_channel.send(embed=embed)
	
	# end of results.
	await start_channel.send("====================")
	
	# allow sending results again
	results_lock = False


# get bot token from file
with open('erb-token.txt') as f:
	botkey = f.readline()

client.run(botkey)
