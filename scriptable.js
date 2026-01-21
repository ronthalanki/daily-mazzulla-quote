// List of quotes
let quotes = [
  "I told Charles when he left, 'I'm not talking to you during the season. I'm not waving to you at the national anthem. I'm not doing that. You're an enemy.' So he breached NBA rules and came into the assistant coach locker room and forced me to give him a hug. That could easily be a psychological tell that knocks you off your game competitively. So he knew what he was doing.",
"The biggest thing that we rob people of, from an entertainment standpoint, is you can't fight anymore. I wish you could bring back fighting. I just don't get why some sports are allowed to clear the benches. They have bats and weapons, we don't. We just have a ball. The other sport has one of the hardest surfaces and playing instruments in pucks and sticks and we're not allowed to throw down a little bit?",
"Zero. No pressure. We're all going to be dead soon, and it really doesn't matter anymore, so there's zero pressure.",
"There's nothing anyone in this circle can do to me that's gonna impact my identity and who I am as a person or a coach. We're either gonna win or we're not, and 40 years from now, none of you are invited to my funeral and that's it.",
"People are gonna say the target is on our back, but I hope it's right on our forehead in between our eyes. I hope I can see the red dot.",
"Before I forget, no one's ever asked me what my favorite scene from 'The Town' was. I know you guys all know that's my favorite movie, but no one's ever been curious about what my favorite scene is? My favorite one is Doug MacRay is getting ready to leave town, and he skips by the FBI's car and leaves a nice, well-thought-out handwritten note underneath the antenna, and then gets out of town. That's my favorite scene.",
"If we ever decided to rob Fenway, I was like, 'We could probably really get away with this.' How could you not go to Fenway and think you couldn't rob it?",
"Ever seen 'Spider-Man'? … 'Into the Spider-Verse'? There's like, 20 different Spider-Men? That's like our team.",
"I would just go until I die. -- Mazzulla on running a marathon",
"Mazzulla on what he saw after Brown took off mask: 'His face'",
"It's beautiful. You should get booed. To me, it's the ultimate compliment.",
"The animal kingdom is the most pure form of hierarchy and role definition that there is.",
"We're all villains in someone's eyes.",
"I wouldn't say I enjoyed the offseason. I enjoyed the parade.",
"I'm always up to get knocked out. I think that's important, too. If you can't go through the day hoping you don't get knocked out, I don't know what do you do.",
"There's no fouls in a war. You either die or you don't.",
"It ended up being a great experience for me. I had to do six hours of treatment in order to coach the next game without too much of a limp because I could not walk. But I tell you what, it was one of the best things that could happen to me for the rest of the season because it put me in this fight or flight mentality to where I just could not relax... It was awesome. I'm thinking about maybe getting hurt every All-Star break. - Mazzula on his torn meniscus",
"When he won coach of the month, I said 'Hey, congratulations.' And he just looked at me and said, 'Nobody cares.'",
"It's beautiful. -- Mazzulla on no Celtics players being finalists for awards.",
"Save yourself the rest of the question. I don't really care.",
"I like in cricket that you can just keep wearing the pitcher down by fouling off on purpose. It's like a huge mental psychological component to just wearing this guy's arm out by just fouling foul balls until he can't pitch anymore. I love the idea of that.",
"'Stop fouling.' Wait, that's it? 'Yes, that’s exactly what I said.'",
"Joe Mazzulla on Jayson Tatum's scary fall after Caleb Martin's hard foul in game 1: 'I was kind of excited about the whole situation. I enjoyed watching it.'",
"[Shammgod] said Mazzulla watched so much game film that Shammgod and the other assistants began to have concerns about his mental health. So they convinced him to sit down with them after long days of work and watch an hour of regular television.",
"Joe Mazzulla just walked past Marcus Smart in the locker room, did a full somersault in front of him, turned and said 'you can’t do that.' Then walked out.",
"Expect for it to be difficult. Don’t wish for it to be anything other than what it is, and you respond accordingly",
"Zero, feel zero difference. And I think if you’re ever lucky to do again, when it does feel different — that’s when I’d rather not do it anymore.",
"We’re either gonna win or we’re not, and 40 years from now, none of you are invited to my funeral and that’s it.",
"I am the worst coach ever.” — Mazzulla leaving a Zoom conference call with the media in May 2023.",
"Everybody wants to win until it’s really time to win. And then you have to nut up and do a lot of [expletive] that you don’t want to do.” — Mazzulla on the Celtics’ mindset during the playoffs",
"Unless they changed the light bulbs in the arena, they won’t be any brighter than they were last series. - Mazzulla on the bright lights of playing in the NBA Finals",
"What do you like about the City Connect jersey? And his response, 'they say Celtics on them.'",
"Placing a sand castle in the film room to remind players that, like a sand castle washing away on the beach every morning, the team needs to build new success each day.",
"I don’t care. Whatever the rules are we will find a way to follow them and manipulate them at the same time.",
"When asked about what he expects for a Game 4 playoff game. Joe: 'An absolute war.' Reporter: More than tonight? Joe: 'I hope so'",
"I was like, '(The wolf) didn't have a good enough relationship with him'",
"Mazzula doesn't use revolving doors because 'if one of them gets stuck, then you're just a sitting duck.'",
"I always try to find a nice car and park near it, because I know nice cars try to park far away. I just want to piss that guy off",
"On the expectations for JT to return, Joe: 'I failed medical school'"
];

// Pick a quote based on the day
let today = new Date();
let dayOfYear = Math.floor(
  (today - new Date(today.getFullYear(), 0, 0)) / 1000 / 60 / 60 / 24
);
let quote = quotes[dayOfYear % quotes.length]; // rotate through quotes daily

// Create the widget
let widget = new ListWidget();// 
widget.backgroundColor = new Color("#007A33");


// Add the quote
let quoteText = widget.addText(quote);
quoteText.textColor = Color.white();
quoteText.font = Font.systemFont(16);
quoteText.centerAlignText();

// Show widget
Script.setWidget(widget);
Script.complete();