/// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

import {Ownable} from '@openzeppelin/contracts/access/Ownable.sol';
import {ReentrancyGuard} from '@openzeppelin/contracts/utils/ReentrancyGuard.sol';
import {IERC20} from '@openzeppelin/contracts/token/ERC20/IERC20.sol';

import {GaussianRNG} from './vendor/GaussianRNG.sol';
import {IAgentV1} from './interfaces/IAgentV1.sol';
import {IGameV1} from './interfaces/IGameV1.sol';
import {IHamsterRaceV1} from './interfaces/IHamsterRaceV1.sol';
import {Conversion} from './libraries/Conversion.sol';
import {AgentDirectoryV1} from './AgentDirectoryV1.sol';
import {OGsNFT} from './OGsNFT.sol';

contract HamsterRaceV1 is IHamsterRaceV1, Ownable, ReentrancyGuard, GaussianRNG {
    using Conversion for int256;
    
    OGsNFT public immutable NFT;
    AgentDirectoryV1 public immutable DIRECTORY;

    // the grid size should be odd, so that the center is reachable
    uint256 private constant GRID_SIZE = 5;
    uint256 private constant NUM_PLAYERS = 2;
    uint256 private constant NUM_ACTIONS = 4; // l, r, u, d
    uint256 private constant GAME_FAILURE_STEPS = 100;
    uint256 private constant LEARNING_RATE = 50; // 50%
    uint256 private constant DISCOUNT_FACTOR = 70; // 70%
    uint256 private constant FEE_DENOMINATOR = 10000;
    uint256 private constant MAX_FEE_PERCENT = 1000; // 10%
    uint256 private constant MAX_RACES_PER_DAY = 500;
    uint256 private constant MAX_RACES_PER_HOUR = 25;
    int256 private constant REWARD_DENOMINATOR = 1e18;

    uint256 public raceId;

    address public feeReceiver;
    uint256 public feePercent = 500; // 5%
    uint256 public commitmentLockPeriod = 1 days;
    
    bool public isRacingEnabled = false;
    bool public isRoundTwoEnabled = false;

    mapping(IERC20 => bool) public enabledBetTokens;
    mapping(uint256 => bool) public enabledBetSizes;
    mapping(address => bool) public enabledHamsterAgents;

    /// commitment hash => commitment
    mapping(bytes32 => RaceCommitment) public raceCommitments;
    /// commitment hash => commitment lock start
    mapping(bytes32 => uint256) public commitmentLock;
    /// token id => time period => race count
    mapping(uint256 => mapping(uint256 => uint256)) public racesPerPeriod;
    /// token id => cooldown end timestamp
    mapping(uint256 => uint256) public cooldownEnd;
    /// commitment hash => count used
    mapping(bytes32 => uint256) public countUsed;

    constructor(
        OGsNFT _nft,
        AgentDirectoryV1 _directory,
        address _feeReceiver
    ) Ownable(msg.sender) {
        NFT = _nft;
        DIRECTORY = _directory;
        feeReceiver = _feeReceiver;
    }

    /// @inheritdoc IHamsterRaceV1
    function isAgentInCooldown(uint256 tokenId) external view returns (bool) {
        return cooldownEnd[tokenId] > block.timestamp;
    }

    /// @inheritdoc IHamsterRaceV1
    function isValidHamsterAgent(address agent) public view returns (bool) {
        return enabledHamsterAgents[agent];
    }

    /// @inheritdoc IHamsterRaceV1
    function isValidCommitment(
        IAgentV1 agent,
        IERC20 betToken,
        uint256 tokenId,
        uint256 betSize,
        bytes32 commitmentHash
    ) external view returns (bool valid) {
        RaceCommitment memory rc = raceCommitments[commitmentHash];
        bool hasManualUpdate = agent.hasManualUpdates(address(this), tokenId);
        bool raceHasManualUpdate = IAgentV1(rc.agent).hasManualUpdates(address(this), rc.tokenId);

        uint256 cooldown = cooldownEnd[rc.tokenId];
        if (cooldown > block.timestamp) {
            revert AgentInCooldown(cooldown - block.timestamp);
        }     
        
        if (raceHasManualUpdate != hasManualUpdate) {
            revert IncompatibleAgents(address(agent), address(rc.agent));
        }
        
        if (address(betToken) != rc.betToken) {
            revert InvalidBetToken(address(betToken));
        }

        if (betSize != rc.betSize) {
            revert InvalidBetSize(betSize);
        }

        if (rc.deadline != 0 && rc.deadline < block.timestamp) {
            revert CommitmentExpired(commitmentHash);
        }

        if (tokenId == rc.tokenId) {
            revert DuplicatePet(rc.tokenId);
        }

        if (countUsed[commitmentHash] + 1 > rc.count) {
            revert CommitmentOverused(commitmentHash);
        }

        if (isRoundTwoEnabled) {
            return true;
        } else if (tokenId > 499 || rc.tokenId > 499) {
            revert InvalidRound();
        }

        return true;
    }

    /// @inheritdoc IHamsterRaceV1
    function getDefinition() public pure returns (bytes32[] memory game) {
        game = new bytes32[](4);
        game[0] = bytes32(GRID_SIZE * GRID_SIZE);
        game[1] = bytes32(NUM_ACTIONS);
        game[2] = bytes32(LEARNING_RATE);
        game[3] = bytes32(DISCOUNT_FACTOR);
        return game;
    }

    /// @inheritdoc IHamsterRaceV1
    function getReward(
        uint256 newXPos,
        uint256 newYPos
    ) public pure returns (bytes32[] memory reward) {
        int256 newDistance = distance(newXPos, newYPos);
        bool hasWon = newXPos == GRID_SIZE / 2 && newYPos == GRID_SIZE / 2;

        reward = new bytes32[](1);

        if (hasWon) {
            // Player reached the center
            reward[0] = int256(100 * REWARD_DENOMINATOR).convertToBytes();
        } else {
            // Manhattan distance to the center
            reward[0] = int256(-newDistance * REWARD_DENOMINATOR).convertToBytes();
        }

        return reward;
    }

    /// @inheritdoc IHamsterRaceV1
    function setFeeReceiver(address _feeReceiver) external onlyOwner {
        feeReceiver = _feeReceiver;
        emit FeeReceiverSet(_feeReceiver);
    }
    
    /// @inheritdoc IHamsterRaceV1
    function setFeePercent(uint256 _feePercent) external onlyOwner {
        if (_feePercent > MAX_FEE_PERCENT) revert FeePercentTooHigh(MAX_FEE_PERCENT);
        feePercent = _feePercent;
        emit FeePercentSet(_feePercent);
    }

    /// @inheritdoc IHamsterRaceV1
    function setCommitmentLockPeriod(uint256 _commitmentLockPeriod) external onlyOwner {
        if (_commitmentLockPeriod > 1 days) revert InvalidCommitmentLockPeriod(1 days);
        commitmentLockPeriod = _commitmentLockPeriod;
        emit CommitmentLockPeriodSet(_commitmentLockPeriod);
    }

    /// @inheritdoc IHamsterRaceV1
    function enableBetToken(IERC20 _betToken) external onlyOwner {
        enabledBetTokens[_betToken] = true;
        emit BetTokenEnabled(address(_betToken));
    }

    /// @inheritdoc IHamsterRaceV1
    function disableBetToken(IERC20 _betToken) external onlyOwner {
        enabledBetTokens[_betToken] = false;
        emit BetTokenDisabled(address(_betToken));
    }

    /// @inheritdoc IHamsterRaceV1
    function enableBetSize(uint256 _betSize) external onlyOwner {
        enabledBetSizes[_betSize] = true;
        emit BetSizeEnabled(_betSize);
    }

    /// @inheritdoc IHamsterRaceV1
    function disableBetSize(uint256 _betSize) external onlyOwner {
        enabledBetSizes[_betSize] = false;
        emit BetSizeDisabled(_betSize);
    }

    /// @inheritdoc IHamsterRaceV1
    function enableRacing() external onlyOwner {
        if (isRacingEnabled) revert RacingAlreadyEnabled();

        isRacingEnabled = true;
        emit RacingEnabled();
    }

    /// @inheritdoc IHamsterRaceV1
    function disableRacing() external onlyOwner {
        if (!isRacingEnabled) revert RacingAlreadyDisabled();

        isRacingEnabled = false;
        emit RacingDisabled();
    }

    /// @inheritdoc IHamsterRaceV1
    function enableRoundTwoRacing() external onlyOwner {
        if (isRoundTwoEnabled) revert InvalidRound();

        isRoundTwoEnabled = true;
        emit RoundTwoRacingEnabled();
    }

    /// @inheritdoc IHamsterRaceV1
    function whitelistHamsterAgent(address agent) external onlyOwner {
        enabledHamsterAgents[agent] = true;
    }

    /// @inheritdoc IHamsterRaceV1
    function banHamsterAgent(address agent) external onlyOwner {
        enabledHamsterAgents[agent] = false;
    }

    /// @inheritdoc IHamsterRaceV1
    function commitToRace(
        IAgentV1 agent,
        IERC20 betToken,
        uint256 tokenId,
        uint256 betSize,
        uint64 deadline,
        uint64 count
    ) public nonReentrant returns (bytes32 commitmentHash) {
        if (!isRacingEnabled) {
            revert RacingNotEnabled();
        }

        if (tokenId > 5556) {
            revert InvalidTokenId(tokenId);
        }

        if (!enabledBetTokens[betToken]) {
            revert InvalidBetToken(address(betToken));
        }

        if (!enabledBetSizes[betSize]) {
            revert InvalidBetSize(betSize);
        }

        if (deadline != 0 && deadline < block.timestamp + commitmentLockPeriod) {
            revert InvalidCommitmentDeadline(commitmentLockPeriod);
        }

        uint256[] memory rng = getRNG(uint256(keccak256(abi.encodePacked(
            block.prevrandao,
            block.number,
            block.timestamp,
            count,
            deadline,
            betSize,
            betToken,
            tokenId,
            agent,
            msg.sender
        ))), 1, 1);
        uint128 rngSeed = uint128(rng[0]);

        RaceCommitment memory rc = RaceCommitment(
            msg.sender,
            address(agent),
            address(betToken),
            tokenId,
            betSize,
            deadline,
            count,
            rngSeed
        );

        betToken.transferFrom(msg.sender, address(this), betSize * uint256(count));
        
        commitmentHash = keccak256(abi.encodePacked(
            msg.sender,
            agent,
            betToken,
            tokenId,
            betSize,
            deadline,
            count,
            rngSeed
        ));
        raceCommitments[commitmentHash] = rc;
        commitmentLock[commitmentHash] = block.timestamp;

        emit PlayerCommitted(rc, commitmentHash);
    }

    /// @inheritdoc IHamsterRaceV1
    function cancelCommitment(bytes32 commitmentHash) external nonReentrant {
        RaceCommitment memory rc = raceCommitments[commitmentHash];

        if (rc.player != msg.sender) {
            revert InvalidCommitmentPlayer();
        }

        uint256 lockedUntil = commitmentLock[commitmentHash] + commitmentLockPeriod;
        if (lockedUntil < block.timestamp) {
            revert CommitmentLocked(lockedUntil);
        }

        uint256 unusedCount = uint256(rc.count - countUsed[commitmentHash]);
        if (unusedCount == 0) {
            revert CommitmentOverused(commitmentHash);
        }

        IERC20(rc.betToken).transferFrom(address(this), rc.player, rc.betSize * unusedCount);

        countUsed[commitmentHash] = rc.count;
    }

    /// @inheritdoc IHamsterRaceV1
    function executeRace(
        bytes32[] memory commitmentHashes
    ) public nonReentrant {
        if (!isRacingEnabled) {
            revert RacingNotEnabled();
        }

        if (commitmentHashes.length != NUM_PLAYERS) {
            revert InvalidCommitmentLength(commitmentHashes.length, NUM_PLAYERS);
        }

        RaceCommitment[] memory commitments = new RaceCommitment[](NUM_PLAYERS);
        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            commitments[i] = raceCommitments[commitmentHashes[i]];
        }

        uint256 _raceId = raceId++;
        bool hasManualUpdates = IAgentV1(commitments[0].agent).hasManualUpdates(
            address(this),
            commitments[0].tokenId
        );

        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            updateCooldown(commitments[i].tokenId, commitmentHashes[i]);

            IAgentV1 ownerAgent = DIRECTORY.getAgent(commitments[i].tokenId, IGameV1(this));
            if (
                commitments[i].agent != address(ownerAgent) || 
                !isValidHamsterAgent(commitments[i].agent)
            ) {
                revert InvalidHamsterAgent(commitments[i].agent);
            }

            uint256 commitmentCount = countUsed[commitmentHashes[i]] + 1;
            if (commitmentCount > commitments[i].count) {
                revert CommitmentOverused(commitmentHashes[i]);
            }

            countUsed[commitmentHashes[i]] = commitmentCount;
            
            if (commitments[i].deadline != 0 && commitments[i].deadline < block.timestamp) {
                revert CommitmentExpired(commitmentHashes[i]);
            }

            for (uint256 j = i + 1; j < NUM_PLAYERS; j++) {
                if (commitments[i].tokenId == commitments[j].tokenId) {
                    revert DuplicatePet(commitments[i].tokenId);
                }
            }

            if (i == 0) continue;

            if (commitments[i].betSize != commitments[0].betSize) {
                revert InvalidBetSize(commitments[i].betSize);
            }

            if (commitments[i].betToken != commitments[0].betToken) {
                revert InvalidBetToken(commitments[i].betToken);
            }

            bool raceHasManualUpdate = IAgentV1(commitments[i].agent).hasManualUpdates(
                address(this),
                commitments[i].tokenId
            );          
            
            if (raceHasManualUpdate != hasManualUpdates) {
                revert IncompatibleAgents(address(commitments[0].agent), address(commitments[i].agent));
            }
        }
        
        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            if (isRoundTwoEnabled) break;

            if (commitments[i].tokenId > 499) {
                revert InvalidRound();
            }
        }

        uint256[] memory tokenIds;
        address[] memory agents;
        uint128[] memory rngSeeds;
        (tokenIds, agents, rngSeeds) = randomizeOrder(commitmentHashes, commitments, _raceId);

        uint256 totalBetSize = commitments[0].betSize * NUM_PLAYERS;
        uint256 fee = totalBetSize * feePercent / FEE_DENOMINATOR;
        (uint256 steps, uint256 winningTokenId) = race(tokenIds, agents, rngSeeds);

        address winner;
        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            if (commitments[i].tokenId == winningTokenId) {
                winner = commitments[i].player;
                break;
            }
        }

        IERC20(commitments[0].betToken).approve(address(this), totalBetSize);
        IERC20(commitments[0].betToken).transferFrom(address(this), feeReceiver, fee);
        IERC20(commitments[0].betToken).transferFrom(address(this), winner, totalBetSize - fee);

        emit RaceFinished(
            winningTokenId,
            winner,
            msg.sender,
            address(commitments[0].betToken),
            commitments[0].betSize,
            _raceId,
            steps,
            commitmentHashes
        );
    }

    function updateCooldown(uint256 tokenId, bytes32 commitmentHash) private {
        uint256 cooldown = cooldownEnd[tokenId];
        if (cooldown > block.timestamp) {
            revert AgentInCooldown(cooldown - block.timestamp);
        }

        if (commitmentLock[commitmentHash] == block.timestamp) {
            revert AgentInCooldown(0);
        }

        uint256 dayStart = block.timestamp / 1 days * 1 days; // truncate

        uint256 races = racesPerPeriod[tokenId][dayStart] + 1;
        racesPerPeriod[tokenId][dayStart] = races;

        if (block.timestamp + 1 hours < dayStart + 1 days && races % MAX_RACES_PER_HOUR == 0) {
            cooldownEnd[tokenId] = block.timestamp + 1 hours;
        } else if (races % MAX_RACES_PER_DAY == 0) {
            cooldownEnd[tokenId] = dayStart + 1 days;
        }
    }

    function race(
        uint256[] memory tokenIds,
        address[] memory agents,
        uint128[] memory rngSeeds
    ) private returns (uint256 steps, uint256 winningTokenId) {
        bytes32[] memory definition = getDefinition();
        HamsterPosition[] memory positions = initializeRace();
        bool hasWon;

        for (steps = 1; steps < GAME_FAILURE_STEPS; steps++) {
            for (uint256 i = 0; i < NUM_PLAYERS; i++) {
                bytes32[] memory state = toRaceState(positions[i]);
                bytes32[] memory action = IAgentV1(agents[i]).selectAction(
                    tokenIds[i],
                    bytes32(uint256(rngSeeds[i]++)),
                    definition,
                    state
                );

                (positions[i], hasWon) = makeMove(positions[i], uint256(action[0]));

                bytes32[] memory nextState = toRaceState(positions[i]);
                bytes32[] memory reward = getReward(
                    positions[i].xPos,
                    positions[i].yPos
                );

                IAgentV1(agents[i]).observe(
                    tokenIds[i],
                    definition,
                    state,
                    action,
                    nextState,
                    reward
                );

                if (hasWon) {
                    return (steps, tokenIds[i]);
                }
            }
        }

        revert GameFailed(steps);
    }

    function toRaceState(
        HamsterPosition memory position
    ) private pure returns (bytes32[] memory state) {
        state = new bytes32[](1);
        state[0] = bytes32(position.xPos * GRID_SIZE + position.yPos);
        return state;
    }

    function initializeRace() private pure returns (HamsterPosition[] memory positions) {
        positions = new HamsterPosition[](NUM_PLAYERS);
        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            if (i % 4 == 0) {
                positions[i] = HamsterPosition(0, 0);
            } else if (i % 4 == 1) {
                positions[i] = HamsterPosition(0, GRID_SIZE - 1);
            } else if (i % 4 == 2) {
                positions[i] = HamsterPosition(GRID_SIZE - 1, 0);
            } else {
                positions[i] = HamsterPosition(GRID_SIZE - 1, GRID_SIZE - 1);
            }
        }
    }

    function makeMove(
        HamsterPosition memory position,
        uint256 action
    ) private pure returns (HamsterPosition memory, bool hasWon) {
        if (action == 0) {
            if (position.xPos > 0) {
                position.xPos--;
            }
        } else if (action == 1) {
            if (position.xPos < GRID_SIZE - 1) {
                position.xPos++;
            }
        } else if (action == 2) {
            if (position.yPos > 0) {
                position.yPos--;
            }
        } else if (action == 3) {
            if (position.yPos < GRID_SIZE - 1) {
                position.yPos++;
            }
        }

        return (
            position,
            isCenterGrid(position.xPos, position.yPos)
        );
    }

    function isCenterGrid(
        uint256 xPos,
        uint256 yPos
    ) private pure returns (bool) {
        return xPos == GRID_SIZE / 2 && yPos == GRID_SIZE / 2;
    }

    function randomizeOrder(
        bytes32[] memory commitmentHashes,
        RaceCommitment[] memory commitments,
        uint256 _raceId
    ) private view returns (
        uint256[] memory order,
        address[] memory agents,
        uint128[] memory rngSeeds
    ) {
        uint256 seed = uint256(keccak256(abi.encodePacked(
            _raceId,
            commitmentHashes,
            block.timestamp,
            block.number,
            block.prevrandao
        )));
        uint256[] memory rng = getRNG(seed, factorial(NUM_PLAYERS), 2);
        
        order = new uint256[](NUM_PLAYERS);
        agents = new address[](NUM_PLAYERS);
        rngSeeds = new uint128[](NUM_PLAYERS);
        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            order[i] = commitments[i].tokenId;
            agents[i] = commitments[i].agent;
            rngSeeds[i] = commitments[i].rngSeed + uint128(rng[i]);
        }

        for (uint256 i = 0; i < NUM_PLAYERS; i++) {
            for (uint256 j = i + 1; j < NUM_PLAYERS; j++) {
                if (rng[i * NUM_PLAYERS + j - 1] == 0) {
                    (order[i], order[j]) = (commitments[j].tokenId, commitments[i].tokenId);
                    (agents[i], agents[j]) = (commitments[j].agent, commitments[i].agent);
                }
            }
        }
    }

    function distance(uint256 xPos, uint256 yPos) private pure returns (int256) {
        int256 centerX = int256(GRID_SIZE) / 2;
        int256 centerY = int256(GRID_SIZE) / 2;
        int256 distanceX = abs(int256(xPos) - centerX);
        int256 distanceY = abs(int256(yPos) - centerY);
        return distanceX + distanceY;
    }

    function abs(int256 x) private pure returns (int256) {
        return x >= 0 ? x : -x;
    }

    function factorial(uint256 n) private pure returns (uint256) {
        uint256 result = 1;
        for (uint256 i = 2; i <= n; i++) {
            result *= i;
        }
        return result;
    }

    function emergencyRecover(
        IERC20 token,
        uint256 amount
    ) external onlyOwner {
        if (address(this).balance > 0) {
            payable(msg.sender).transfer(address(this).balance);
        }

        if (amount > 0) {
            token.approve(address(this), amount);
            token.transfer(msg.sender, amount);
        }
    }
}