import discord
from discord.ext import commands
from discord import app_commands
from openai import OpenAI
import asyncio
import traceback
import os
import sys
import json
from datetime import datetime
import aiohttp
from aiohttp import web

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
VOIDAI_API_KEY = "sk-voidai-LHjReN87tQ8Vgdan_jRs7VLkKbYeZO2Rxf05G9yOAwpjLSoHkwGun0V-AjyyrsICQT79O0vgVrt4bn1Gci1PYqxVPC4Jz8KUTAEJXhTEbaDgGzxq1fyTPjhFzchmLuWIIuBaMw"

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN environment variable is not set!")
    print("Please set it using: export DISCORD_TOKEN='your_token_here'")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

client = OpenAI(
    api_key=VOIDAI_API_KEY,
    base_url="https://api.voidai.app/v1",
    max_retries=2,
    timeout=30.0
)

ai_channels = {}
conversation_history = {}
selected_models = {}
aioff_channels = {}
api_status = {}

async def keep_alive():
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="✅ Bot is running", status=200)
    
    async def bot_status(request):
        status = {
            "bot_name": str(bot.user) if bot.user else "Not connected",
            "guilds": len(bot.guilds) if bot.guilds else 0,
            "ai_channels_count": len(ai_channels),
            "status": "online" if bot.is_ready() else "starting",
            "timestamp": datetime.now().isoformat()
        }
        return web.json_response(status)
    
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', bot_status)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    print(f"🌐 Health check server running on port {os.getenv('PORT', 8080)}")

@tree.command(name="setai", description="Set an AI channel")
@app_commands.describe(channel="The channel to set as AI channel")
async def setai(interaction: discord.Interaction, channel: discord.TextChannel):
    ai_channels[interaction.guild.id] = channel.id
    conversation_history[channel.id] = []
    selected_models[channel.id] = "gpt-4.1-nano"
    aioff_channels[channel.id] = False
    api_status[channel.id] = {"working": True, "last_error": None}
    await interaction.response.send_message(f"✅ {channel.mention} is now the AI channel! The bot will automatically respond to all messages in this channel.")

@tree.command(name="aioff", description="Toggle AI responses (ON=only 'ai' role, OFF=everyone)")
async def aioff(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    aioff_channels[channel_id] = not aioff_channels.get(channel_id, False)
    status = "ON (AI will now only respond to users with 'ai' role)" if aioff_channels[channel_id] else "OFF (AI responds to everyone)"
    await interaction.response.send_message(f"✅ aioff toggled: {status}")

@tree.command(name="askai", description="Directly ask the AI a question")
@app_commands.describe(question="The question to ask the AI")
async def askai(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    message_content = f"{interaction.user.display_name}: {question}"
    await process_ai_message(interaction.channel, interaction, message_content, interaction.user)

@tree.command(name="model", description="Select AI model for current channel")
async def model(interaction: discord.Interaction):
    available_models = [
        "gpt-4.1-nano", "gpt-4o-mini", "gpt-4o", "gemini-2.0-flash"
    ]

    class ModelSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=m, value=m) for m in available_models]
            super().__init__(placeholder="Select AI model...", min_values=1, max_values=1, options=options)

        async def callback(self, select_interaction: discord.Interaction):
            if select_interaction.user.id != interaction.user.id:
                await select_interaction.response.send_message("❌ You can't use this menu!", ephemeral=True)
                return
            
            selected_models[select_interaction.channel.id] = self.values[0]
            await select_interaction.response.send_message(f"✅ Model set to `{self.values[0]}`", ephemeral=True)

    class ModelView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(ModelSelect())
            self.timeout = 30

    await interaction.response.send_message("Choose a model for this channel:", view=ModelView())

@tree.command(name="helpai", description="Show all available commands")
async def helpai(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 AI Bot Commands",
        description="All commands use slash (`/`)",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📌 Setup",
        value="`/setai [channel]` - Set an AI channel (bot auto-replies to all messages)\n`/model` - Select AI model",
        inline=False
    )
    
    embed.add_field(
        name="💬 Interaction",
        value="`/askai [question]` - Directly ask the AI\n`/aioff` - Toggle AI responses",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Other",
        value="`/helpai` - Show this help menu",
        inline=False
    )
    
    embed.set_footer(text="Created by Zach and Hitboy")
    await interaction.response.send_message(embed=embed)

@tree.command(name="apistatus", description="Check API status for current channel")
async def apistatus(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    status = api_status.get(channel_id, {"working": False, "last_error": "Not initialized"})
    
    if status["working"]:
        await interaction.response.send_message("✅ API is working properly for this channel.")
    else:
        error_msg = status.get("last_error", "Unknown error")
        await interaction.response.send_message(f"❌ API has issues. Last error: {error_msg}")

@bot.command()
@commands.has_permissions(administrator=True)
async def rf(ctx):
    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    await ctx.send("Enter password to reset (password is `9669`):")
    try:
        msg = await bot.wait_for('message', check=check, timeout=30)
        if msg.content.strip() == '9669':
            await ctx.send("Password correct. Shutting down all Python scripts and deleting messages...")
            
            try:
                await ctx.message.delete()
                await msg.delete()
            except:
                pass

            deleted = 0
            async for message in ctx.channel.history(limit=None):
                try:
                    await message.delete()
                    deleted += 1
                    if deleted % 10 == 0:
                        await asyncio.sleep(1)
                except:
                    pass

            guild = ctx.guild
            for member in guild.members:
                if member != ctx.me and not member.guild_permissions.administrator:
                    try:
                        await member.kick(reason="RF command executed.")
                        await asyncio.sleep(0.5)
                    except:
                        pass

            await asyncio.sleep(1)
            await ctx.send("All done. Shutting down bot.")
            await bot.close()
            os._exit(0)
        else:
            await ctx.send("Incorrect password.")
    except asyncio.TimeoutError:
        await ctx.send("Timeout. Command cancelled.")

async def make_api_call(model_to_use, messages_to_send, channel_id):
    try:
        loop = asyncio.get_event_loop()
        
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model_to_use,
                    messages=messages_to_send,
                    max_tokens=500,
                    temperature=0.7,
                    timeout=15.0
                )
            ),
            timeout=20.0
        )
        
        api_status[channel_id] = {"working": True, "last_error": None}
        return response
        
    except asyncio.TimeoutError:
        api_status[channel_id] = {"working": False, "last_error": "Request timed out after 20 seconds"}
        raise Exception("The AI request timed out. The API might be down or slow.")
    except Exception as e:
        error_msg = str(e)
        api_status[channel_id] = {"working": False, "last_error": error_msg}
        if "500" in error_msg or "Internal Server Error" in error_msg:
            raise Exception("The AI service is currently experiencing issues. Please try again later.")
        else:
            raise Exception(f"API Error: {error_msg[:100]}")

async def get_fallback_response(user_message, channel_id):
    fallback_responses = [
        "I'm currently experiencing technical difficulties with my AI service. Please try again in a few minutes!",
        "The AI service is temporarily unavailable. Try asking me something else!",
        "Sorry, I can't connect to my AI brain right now. Maybe ask me later?",
        "Hmm, my AI connection seems to be down. Want to try again in a bit?",
        "I'm having trouble reaching the AI servers. Please try your question again shortly!"
    ]
    
    user_msg_lower = user_message.lower()
    
    if any(word in user_msg_lower for word in ["hello", "hi", "hey", "greetings"]):
        return "Hello! I'm here, but my advanced AI features are currently offline."
    elif any(word in user_msg_lower for word in ["who", "what", "where", "when", "why", "how"]):
        return "That's a great question! Normally I'd answer with AI, but the service is temporarily down."
    elif "joke" in user_msg_lower:
        return "Why don't scientists trust atoms? Because they make up everything! 😄 (PS: My AI service is down, but I still know some jokes!)"
    
    import random
    return random.choice(fallback_responses)

async def process_ai_message(channel, ctx_or_interaction, user_message, author):
    channel_id = channel.id

    if aioff_channels.get(channel_id, False):
        user_roles = [role.name.lower() for role in author.roles]
        if "ai" not in user_roles:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send("❌ AI is in 'aioff' mode. Only users with 'ai' role can use AI features.", ephemeral=True)
            else:
                await ctx_or_interaction.channel.send(f"{author.mention} ❌ AI is in 'aioff' mode. Only users with 'ai' role can use AI features.")
            return

    conversation_history.setdefault(channel_id, [])

    clean_message = user_message
    if " says: " in clean_message:
        clean_message = clean_message.split(" says: ")[1]
    elif ": " in clean_message:
        clean_message = clean_message.split(": ", 1)[1]
    
    conversation_history[channel_id].append({"role": "user", "content": clean_message})

    model_to_use = selected_models.get(channel_id, "gpt-3.5-turbo")

    if isinstance(ctx_or_interaction, discord.Interaction):
        thinking_msg = await ctx_or_interaction.followup.send("🤖 Thinking.", wait=True)
    else:
        thinking_msg = await ctx_or_interaction.reply("🤖 Thinking.")

    try:
        async def animate_thinking(msg):
            dots = ["🤖 Thinking.", "🤖 Thinking..", "🤖 Thinking..."]
            i = 0
            while not hasattr(animate_thinking, "stop"):
                await msg.edit(content=dots[i % 3])
                i += 1
                await asyncio.sleep(0.8)

        animate_thinking.stop = False
        animate_task = asyncio.create_task(animate_thinking(thinking_msg))

        system_prompt = {"role": "system", "content": "You are an AI assistant created by Zach and Hitboy. Respond helpfully and naturally to users. Keep responses concise and relevant."}
        messages_to_send = [system_prompt] + conversation_history[channel_id][-10:]

        response = None
        ai_reply = None
        
        try:
            response = await make_api_call(model_to_use, messages_to_send, channel_id)
            
            try:
                ai_reply = response.choices[0].message.content
            except:
                try:
                    ai_reply = response.choices[0].get('message', {}).get('content')
                except:
                    ai_reply = str(response)

        except Exception as api_error:
            ai_reply = await get_fallback_response(clean_message, channel_id)

        animate_thinking.stop = True
        await animate_task

        if ai_reply:
            if response is not None:
                conversation_history[channel_id].append({"role": "assistant", "content": ai_reply})
                if len(conversation_history[channel_id]) > 20:
                    conversation_history[channel_id] = conversation_history[channel_id][-20:]
            
            if len(ai_reply) > 2000:
                chunks = [ai_reply[i:i+2000] for i in range(0, len(ai_reply), 2000)]
                await thinking_msg.edit(content=chunks[0])
                for chunk in chunks[1:]:
                    await channel.send(chunk)
            else:
                await thinking_msg.edit(content=ai_reply)
        else:
            await thinking_msg.edit(content="⚠️ No reply from AI.")
            
    except Exception as e:
        animate_thinking.stop = True
        try:
            await animate_task
        except:
            pass
            
        error_msg = f"❌ Sorry, I encountered an error: {str(e)[:50]}..."
        await thinking_msg.edit(content=error_msg)
        traceback.print_exc()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    guild_id = message.guild.id if message.guild else None
    if guild_id is None:
        return
    
    channel_id = message.channel.id
    
    user_roles = [role.name.lower() for role in message.author.roles]
    
    aioff_active = aioff_channels.get(channel_id, False)
    
    if guild_id in ai_channels and channel_id == ai_channels[guild_id]:
        if aioff_active:
            if "ai" not in user_roles:
                return
        
        message_content = f"{message.author.display_name}: {message.content}"
        await process_ai_message(message.channel, message, message_content, message.author)

@bot.event
async def on_ready():
    print(f'✅ {bot.user} has connected to Discord!')
    print(f'✅ Serving {len(bot.guilds)} guilds')
    
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
    
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/helpai"))
    
    asyncio.create_task(keep_alive())
    print("🌐 Health check server started")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    try:
        synced = await tree.sync()
        await ctx.send(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        await ctx.send(f"❌ Error syncing: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument. Usage: `{ctx.command.signature}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Bad argument. Please check your input.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(f"❌ You don't have permission to use this command.")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)[:100]}")
        traceback.print_exc()

async def test_api_connection():
    print("🤖 Testing API connection...")
    try:
        test_client = OpenAI(
            api_key=VOIDAI_API_KEY,
            base_url="https://api.voidai.app/v1",
            timeout=10.0
        )
        
        test_response = test_client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=5
        )
        print("✅ API connection test successful!")
        return True
    except Exception as e:
        print(f"⚠️ API connection test failed: {str(e)[:200]}")
        print("⚠️ The bot will use fallback responses if the API is down.")
        return False

if __name__ == "__main__":
    print("🤖 Starting AI Discord Bot...")
    
    api_working = asyncio.run(test_api_connection())
    if not api_working:
        print("⚠️ Warning: API may not be working properly. Check your API key and network connection.")
    
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ Invalid Discord token. Please check your token.")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
