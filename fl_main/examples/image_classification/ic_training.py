from typing import Tuple
import random

import torch
import torchvision
import torchvision.transforms as transforms


class DataManger:
    """
    Managing training/test data
    Note: Singleton Pattern
    """
    _singleton_dm = None

    @classmethod
    def dm(cls, th: int = 0):
        if not cls._singleton_dm and th > 0:
            cls._singleton_dm = cls(th)
        return cls._singleton_dm

    def __init__(self, cutoff_th: int):
        transform = transforms.Compose(
            [transforms.ToTensor(),
             transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])

        trainset = torchvision.datasets.CIFAR10(root='./data', train=True,
                                                download=True, transform=transform)

        testset = torchvision.datasets.CIFAR10(root='./data', train=False,
                                               download=True, transform=transform)

        self.trainloader = torch.utils.data.DataLoader(trainset, batch_size=4,
                                                       shuffle=True, num_workers=2)

        self.testloader = torch.utils.data.DataLoader(testset, batch_size=4,
                                                      shuffle=False, num_workers=2)

        self.classes = ('plane', 'car', 'bird', 'cat', 'deer',
                        'dog', 'frog', 'horse', 'ship', 'truck')

        self.cutoff_threshold = cutoff_th


    def get_random_images(self, is_train: bool = False) -> Tuple:
        """
        Retrun a batch of images and labels
        Those can be used to show examples for demos
        :param is_train:
        :return:
        """
        if is_train:  # if it requires training data
            ldr = self.trainloader
        else:  # test data
            ldr = self.testloader
        imgs, labels = iter(ldr).next()

        return imgs, labels


def execute_ic_training(dm, net, criterion, optimizer):
    """
    Training routine
    :param dm: DataManager providing access to training data
    :param net: CNN
    :param criterion:
    :param optimizer:
    :return:
    """
    # To simulate the scenarios where each agent has less number of data
    # train on first N batches up to cutoff threshold (consecutive, not random)
    for epoch in range(1):
        running_loss = 0.0
        num_trained_batches = 0
        
        for i, data in enumerate(dm.trainloader):
            # Stop after reaching cutoff threshold
            if num_trained_batches >= dm.cutoff_threshold:
                break
            
            # get the inputs; data is a list of [inputs, labels]
            inputs, labels = data

            # zero the parameter gradients
            optimizer.zero_grad()

            # forward + backward + optimize
            outputs = net(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            # print statistics
            running_loss += loss.item()
            num_trained_batches += 1
            
            if num_trained_batches % 100 == 0:  # print every 100 mini-batches
                avg_loss = running_loss / num_trained_batches
                print(f'[Epoch {epoch + 1}, Batch {num_trained_batches}] avg loss: {avg_loss:.3f}')

    print(f'Training completed: {num_trained_batches} batches trained')
    return net


