import asyncio
from time import time
from typing import Dict
from random import randint, uniform

from discord import Message, SlashCommand, UserCommand, MessageCommand, SubCommand, InvalidData
from discord.ext import commands
from cogs.startup import Config

auto_buy_sub_strings = {
    "Pokeballs: 0": "pb",
    "Pokeballs : 0": "pb",
    "Greatballs: 0": "gb",
    "Ultraballs: 0": "ub",
    "Masterballs: 0": "mb",
}

async def auto_buy(
    bot: commands.Bot,
    config: Config,
    commands: Dict[str, SlashCommand | UserCommand | MessageCommand | SubCommand],
    message: Message,
) -> None:
    to_buy = [
        auto_buy_sub_strings[string]
        for string in list(auto_buy_sub_strings.keys())
        if string in message.embeds[0].footer.text
    ]

    if to_buy and config.auto_buy[to_buy[0]] != 0 and not bot.auto_buy_queued:
        bot.auto_buy_queued = True
        await asyncio.sleep(2 + randint(0, config.suspicion_avoidance) / 1000)
        task = asyncio.create_task(
            commands["shop buy"](item=to_buy[0], amount=config.auto_buy[to_buy[0]])
        )
        bot.auto_buy_queued = False
        await task

class Hunting(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config: Config = bot.config

    @commands.Cog.listener()
    async def on_message(self, message: Message) -> None:
        if not message.interaction:
            return

        if (
            message.interaction.name != "pokemon"
            or message.interaction.user != self.bot.user
            or message.channel.id != self.config.hunting_channel_id
        ):
            return

        if "Please wait" in message.content:
            await asyncio.sleep(self.config.retry_cooldown)
            await asyncio.sleep(randint(0, self.config.suspicion_avoidance) / 1000)
            await self.randomized_pokemon_command()
            return

        if not message.embeds:
            return

        if "You have reached your daily catch limit!" in message.embeds[0].description:
            self.bot.limit = True
            self.bot.hunting_status = "Encounter limit reached!"
            await self.bot.log()
            return

        if "found a wild" not in message.content:
            return

        self.bot.hunting_status = "Grinding..."
        self.bot.encounters += 1
        self.bot.last_hunt = time()
        await self.bot.log()

        name = message.embeds[0].description.split("**")[3]

        # Check for Legendary Pokémon and choose ball based on emoji presence
        if "Legendary" in message.embeds[0].footer.text:
            # Determine if the Legendary Pokémon has been caught or not
            if ":masterball_unlocked:" in message.content:
                ball = "ub"  # Use Ultraball for already caught Pokémon
            elif ":masterball_locked:" in message.content:
                ball = "mb"  # Use Masterball for uncaught Pokémon
            else:
                ball = "ub"  # Default to Ultraball if detection fails
        else:
            # Use the configured ball for other Pokémon based on rarity
            if name in self.config.exception_balls:
                ball = self.config.exception_balls[name]
            else:
                ball = [
                    self.config.balls[rarity]
                    for rarity in list(self.config.balls.keys())
                    if rarity in message.embeds[0].footer.text
                ][-1]


        if ball == "mb" and self.config.auto_buy["mb"] == 0:
            ball = "ub"  # Fallback to Ultra Ball if no Master Ball available
        balls = ["mb", "prb", "ub", "gb", "pb"]
        balls = balls[balls.index(ball):]

        children = [
            child for component in message.components for child in component.children
        ]
        buttons = [
            button for button in children for ball in balls if button.custom_id == ball
        ]

        if not buttons:
            return

        try:
            await asyncio.sleep(randint(0, self.config.suspicion_avoidance) / 1000)
            await buttons[-1].click()
        except InvalidData:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: Message, after: Message) -> None:
        if not after.interaction:
            return

        if (
            after.interaction.name != "pokemon"
            or after.interaction.user != self.bot.user
            or after.channel.id != self.config.hunting_channel_id
            or "found a wild" not in before.content
        ):
            return

        tasks = []

        if "caught" in after.embeds[0].description:
            self.bot.catches += 1
            self.bot.coins_earned += int(
                after.embeds[0].footer.text.split("You earned ")[1].split(" ")[0].replace(",", "")
            )
            await self.bot.log()

            if "has been added to your Pokedex" not in after.embeds[0].description:
                self.bot.duplicates += 1

            if (
                self.config.auto_release_duplicates != 0
                and self.bot.duplicates >= self.config.auto_release_duplicates
            ):
                self.bot.duplicates = 0
                await asyncio.sleep(
                    2 + randint(0, self.config.suspicion_avoidance) / 1000
                )
                tasks.append(
                    asyncio.create_task(
                        self.bot.hunting_channel_commands["release duplicates"]()
                    )
                )

        if "Your next Quest is now ready!" in before.content:
            await asyncio.sleep(1 + randint(0, self.config.suspicion_avoidance) / 1000)
            tasks.append(
                asyncio.create_task(self.bot.hunting_channel_commands["quest info"]())
            )

        tasks.append(
            asyncio.create_task(
                auto_buy(self.bot, self.config, self.bot.hunting_channel_commands, after)
            )
        )

        await asyncio.sleep(self.config.hunting_cooldown)
        await asyncio.sleep(randint(0, self.config.suspicion_avoidance) / 1000)
        await self.randomized_pokemon_command()  # Call the method
        [await task for task in tasks]

    async def randomized_pokemon_command(self) -> None:
        """
        Randomly sends a 'pokemon' command to the bot with efficient delay and improved error handling.
        """
        try:
            # Adding a dynamic delay based on suspicion avoidance and encounter activity
            delay = uniform(3, 5) + randint(0, self.config.suspicion_avoidance) / 1000
            await asyncio.sleep(delay)

            # Wrap in a timeout in case Discord's response takes too long
            try:
                await asyncio.wait_for(self.bot.hunting_channel_commands["pokemon"](), timeout=10)
            except asyncio.TimeoutError:
                # Handle if the command takes too long to respond
                print("Command timed out, retrying after a cooldown.")
                await asyncio.sleep(self.config.retry_cooldown)  # Adjust cooldown if necessary
                await asyncio.wait_for(self.bot.hunting_channel_commands["pokemon"](), timeout=10)
        
        except Exception as e:
            # Log any other errors encountered
            print(f"An error occurred in the pokemon command: {e}")
            await self.bot.log()  # Log the error in the bot's system for better tracking
